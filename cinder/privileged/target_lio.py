#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_log import log as logging

from cinder.cmd import rtstool
from cinder import exception
from cinder.i18n import _
from cinder import privileged

import rtslib_fb

LOG = logging.getLogger(__name__)


def _lookup_target(target_iqn, initiator_iqn):
    try:
        rtsroot = rtslib_fb.root.RTSRoot()
    except rtslib_fb.utils.RTSLibError:
        msg = _('Ensure that configfs is mounted at /sys/kernel/config.')
        raise exception.LIOTargetError(msg)

    # Look for the target
    for t in rtsroot.targets:
        if t.wwn == target_iqn:
            return t
    raise exception.LIOTargetError(
        _('Could not find target %s') % target_iqn)


@privileged.default.entrypoint
def get_targets():
    return rtstool.get_targets()


def _canonicalize_ip(ip):
    if ip.startswith('[') or "." in ip:
        return ip
    return "[" + ip + "]"


def _create(backing_device, name, userid, password, iser_enabled,
            initiator_iqns=None, portals_ips=None, portals_port=3260):
    # List of IPs that will not raise an error when they fail binding.
    # Originally we will fail on all binding errors.
    ips_allow_fail = ()

    try:
        rtsroot = rtslib_fb.root.RTSRoot()
    except rtslib_fb.utils.RTSLibError:
        msg = _('Ensure that configfs is mounted at /sys/kernel/config.')
        raise exception.LIOTargetError(msg)

    # Look to see if BlockStorageObject already exists
    for x in rtsroot.storage_objects:
        if x.name == name:
            # Already exists, use this one
            return

    so_new = rtslib_fb.BlockStorageObject(name=name,
                                          dev=backing_device)

    target_new = rtslib_fb.Target(rtslib_fb.FabricModule('iscsi'), name,
                                  'create')

    tpg_new = rtslib_fb.TPG(target_new, mode='create')
    tpg_new.set_attribute('authentication', '1')

    lun_new = rtslib_fb.LUN(tpg_new, storage_object=so_new)

    if initiator_iqns:
        initiator_iqns = initiator_iqns.strip(' ')
        for i in initiator_iqns.split(','):
            acl_new = rtslib_fb.NodeACL(tpg_new, i, mode='create')
            acl_new.chap_userid = userid
            acl_new.chap_password = password

            rtslib_fb.MappedLUN(acl_new, lun_new.lun, lun_new.lun)

    tpg_new.enable = 1

    # If no ips are given we'll bind to all IPv4 and v6
    if not portals_ips:
        portals_ips = ('0.0.0.0', '[::0]')
        # TODO(emh): Binding to IPv6 fails sometimes -- let pass for now.
        ips_allow_fail = ('[::0]',)

    for ip in portals_ips:
        try:
            # rtslib expects IPv6 addresses to be surrounded by brackets
            portal = rtslib_fb.NetworkPortal(tpg_new, _canonicalize_ip(ip),
                                             portals_port, mode='any')
        except rtslib_fb.utils.RTSLibError:
            raise_exc = ip not in ips_allow_fail
            msg_type = 'Error' if raise_exc else 'Warning'
            msg = (_('%(msg_type)s: creating NetworkPortal: ensure port '
                     '%(port)d on ip %(ip)s is not in use by another service.')
                   % {'msg_type': msg_type, 'port': portals_port, 'ip': ip})
            if raise_exc:
                raise exception.LIOTargetError(msg)
            else:
                LOG.error(msg)
        else:
            try:
                if iser_enabled == 'True':
                    portal.iser = True
            except rtslib_fb.utils.RTSLibError:
                msg = _('Error enabling iSER for NetworkPortal: please ensure '
                        'that RDMA is supported on your iSCSI port %(port)d '
                        'on ip %(ip)s.') % {'port': portals_port, 'ip': ip}
                raise exception.LIOTargetError(msg)


@privileged.default.entrypoint
def create(backing_device, name, userid, password, iser_enabled,
           initiator_iqns=None, portals_ips=None, portals_port=3260):
    return _create(backing_device, name, userid, password, iser_enabled,
                   initiator_iqns=initiator_iqns,
                   portals_ips=portals_ips,
                   portals_port=3260)


def _add_initiator(target_iqn, initiator_iqn, userid, password):
    target = _lookup_target(target_iqn, initiator_iqn)
    tpg = next(target.tpgs)  # get the first one
    for acl in tpg.node_acls:
        # See if this ACL configuration already exists
        if acl.node_wwn.lower() == initiator_iqn.lower():
            # No further action required
            return

    acl_new = rtslib_fb.NodeACL(tpg, initiator_iqn, mode='create')
    acl_new.chap_userid = userid
    acl_new.chap_password = password

    rtslib_fb.MappedLUN(acl_new, 0, tpg_lun=0)


@privileged.default.entrypoint
def add_initiator(target_iqn, initiator_iqn, userid, password):
    return _add_initiator(target_iqn, initiator_iqn, userid, password)


def _delete_initiator(target_iqn, initiator_iqn):
    target = _lookup_target(target_iqn, initiator_iqn)
    tpg = next(target.tpgs)  # get the first one
    for acl in tpg.node_acls:
        if acl.node_wwn.lower() == initiator_iqn.lower():
            acl.delete()
            LOG.debug('Deleted initiator %s', initiator_iqn)
            return

    LOG.debug('delete_initiator: %s ACL not found. Continuing.',
              initiator_iqn)


@privileged.default.entrypoint
def delete_initiator(target_iqn, initiator_iqn):
    _delete_initiator(target_iqn, initiator_iqn)


def _delete(iqn):
    """Delete a target."""
    rtsroot = rtslib_fb.root.RTSRoot()
    for x in rtsroot.targets:
        if x.wwn == iqn:
            x.delete()
            LOG.debug('Deleted target %(iqn)s', {'iqn': iqn})
            break

    for x in rtsroot.storage_objects:
        if x.name == iqn:
            x.delete()
            LOG.debug('Deleted storage object %(iqn)s', {'iqn': iqn})
            break


@privileged.default.entrypoint
def delete(iqn):
    return _delete(iqn)
