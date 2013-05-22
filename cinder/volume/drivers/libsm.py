"""
libstoragemgmt volume driver
Requires libstoragemgmt 0.0.20 ?
"""

import json
import lsm
import os
import tempfile
import urllib

from oslo.config import cfg

from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume import driver

LOG = logging.getLogger(__name__)

lsm_opts = [
    cfg.StrOpt('rbd_pool',
               default='rbd',
               help='the RADOS pool in which rbd volumes are stored'),
    cfg.StrOpt('lsm_uri',
               default=None,
               help='...'),
    cfg.StrOpt('lsm_user',
               default=None,
               help='the RADOS client name for accessing rbd volumes'),
    cfg.StrOpt('lsm_password',
               default=None,
               help='...'),
    cfg.StrOpt('rbd_secret_uuid',
               default=None,
               help='the libvirt uuid of the secret for the rbd_user'
                    'volumes'),
    cfg.StrOpt('volume_tmp_dir',
               default=None,
               help='where to store temporary image files if the volume '
                    'driver does not write them directly to the volume'), ]

VERSION = '1.0'


class LSMDriver(driver.VolumeDriver):
    """Implements libstoragemgmt interface"""
    def __init__(self, *args, **kwargs):
        super(LSMDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(lsm_opts)

        self.lsmclient = lsm.Client('targetd://admin@192.168.175.241', 'targetd')
        self._test_lsm()

        self.pool_name = 'vg-targetd'

        self._stats = dict(
            volume_backend_name='LSM',
            vendor_name='Open Source',
            driver_version=VERSION,
            storage_protocol='iSCSI',
            total_capacity_gb='unknown',
            free_capacity_gb='unknown',
            reserved_percentage=0)

    def _test_lsm(self):
        LOG.debug(self.lsmclient.volumes())
        LOG.debug(self.lsmclient.initiators())

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met"""
        #(stdout, stderr) = self._execute('rados', 'lspools')
        #pools = stdout.split("\n")
        #if self.configuration.rbd_pool not in pools:
        #    exception_message = (_("rbd has no pool %s") %
        #                         self.configuration.rbd_pool)
        #    raise exception.VolumeBackendAPIException(data=exception_message)
        self._test_lsm()
        pass

    def _update_volume_stats(self):
        self._test_lsm()
        stats = dict(
            total_capacity_gb='unknown',
            free_capacity_gb='unknown')
        try:
            pool = self._get_pool(self.pool_name)
            stats['total_capacity_gb'] = pool.total_space / 1024 / 1024 / 1024
            stats['free_capacity_gb'] = pool.free_space / 1024 / 1024 / 1024
        except lsm.LsmError:
            # just log and return unknown capacities
            LOG.exception(_('error refreshing volume stats'))
            pass

        self._stats.update(stats)

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service. If 'refresh' is
           True, run the update first."""
        if refresh:
            self._update_volume_stats()
        return self._stats

    def create_cloned_volume(self, volume, src_vref):
        # TODO
        raise NotImplementedError()

    def _get_pool(self, pool_name):
        for p in self.lsmclient.pools():
            if p.name == pool_name:
                return p
        raise exception.LibSMPoolNotFound(pool_name)

    def _get_initiator(self, initiator_name):
        for i in self.lsmclient.initiators():
            if i.id == initiator_name:
                return i
        raise exception.LibSMInitiatorNotFound(initiator_name)

    def _get_volume(self, volume_id):
        for v in self.lsmclient.volumes():
            if v.id == volume_id:
                return v

        raise exception.LibSMVolumeNotFound(volume_id)

    def _get_volume_by_name(self, volume_name):
         for v in self.lsmclient.volumes():
             if v.name == volume_name:
                 return v

    def create_volume(self, volume):
        """Creates a logical volume."""
        self._test_lsm()

        LOG.debug("creating volume... name: %s, size: %d",
                  volume['name'],
                  volume['size'])

        #LOG.debug("initiators: %s" % self.lsmclient.initiators())

        #try:
        #    LOG.debug("%s", self.lsmclient.pools())
        #except lsm.LsmError as e:
        #    LOG.error("LSM pools Error: %s", e)
        #    raise e

        #try:
        #    LOG.debug("%s", self.lsmclient.volumes())
        #except lsm.LsmError as e:
        #    LOG.error("LSM volumes Error: %s", e)
        #    raise e



        #for p in self.lsmclient.pools():
        #    if p.name == pool_name:
        #        pool = p
        #        break
        pool = self._get_pool(self.pool_name)

        size_in_bytes = volume['size'] * 1024 * 1024 * 1024
        size_in_bytes = 1024 * 1024  # TODO: for testing simplicity
        LOG.debug("original size: %d" % volume['size'])
        LOG.debug("new size (bytes): %d" % size_in_bytes)

        LOG.debug("params")
        LOG.debug("pool: %s" % pool)
        LOG.debug("name: %s" % volume['name'])
        LOG.debug("pd: %s" % lsm.Volume.PROVISION_DEFAULT)

        (j, v) = self.lsmclient.volume_create(pool,
                                           volume['name'],
                                           size_in_bytes,
                                           lsm.Volume.PROVISION_DEFAULT)

        LOG.debug("new volume: %s", v)

        if j is not None:
            LOG.debug("job created...")
            raise LibSMSomethingBroke() # TODO

        pl_ip = self.configuration.iscsi_ip_address
        pl_port = self.configuration.iscsi_port
        pl_target_iqn = self.configuration.iscsi_target_prefix + volume['name']
        pl_portal = 'aslfdjaslfd_portal'

        volume['provider_location'] = "%s:%s,%s %s" % (pl_ip, pl_port, pl_portal, pl_target_iqn)

        # libsm doesn't actually write anything to targetcli at this point,
        # so, let's make it...
        # er, no.  lsmcli -l VOLUMES

        #initiator = 'iqn.2003.01.com.example.eric:test'

        #self.lsmclient.initiator_grant(initiator,
                                       #TYPE_ISCSI,
                                       #v,
                                       #ACCESS_READ_WRITE)

        #if i is not None:
        #    print "something went wrong..."

        #initiator_to_adjust = get_initiator(initiator)

        #username = str(uuid.uuid1())[:8]
        #password = str(uuid.uuid1())[:8]

        #LOG.debug("username: %s, password: %s" % (username, password))

        #self.lsmclient.iscsi_chap_auth(initiator_to_adjust,
        #                               username,
        #                               password,
        #                               None,
        #                               None)

        #return { 'provider_location': volume['provider_location'] }
        return None




    def _clone(self, volume, src_pool, src_image, src_snap):
        self._try_execute('rbd', 'clone',
                          '--pool', src_pool,
                          '--image', src_image,
                          '--snap', src_snap,
                          '--dest-pool', self.configuration.rbd_pool,
                          '--dest', volume['name'])

    def _resize(self, volume):
        size = int(volume['size']) * 1024
        self._try_execute('rbd', 'resize',
                          '--pool', self.configuration.rbd_pool,
                          '--image', volume['name'],
                          '--size', size)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self._clone(volume, self.configuration.rbd_pool,
                    snapshot['volume_name'], snapshot['name'])
        if int(volume['size']):
            self._resize(volume)

    def delete_volume(self, volume):
        """Deletes a logical volume."""

        volume_to_delete = None

        #for v in self.lsmclient.volumes():
        #    if v.name == volume['name']:
        #        volume_to_delete = v
        #        break

        volume_to_delete = self._get_volume_by_name(volume['name'])

        if volume_to_delete is None:
            LOG.error("volume %s not found" % volume['name'])
            raise exception.LibSMVolumeNotFound(volume['name'])  # TODO

        self.lsmclient.volume_delete(volume_to_delete)
        
    def create_snapshot(self, snapshot):
        """Creates an rbd snapshot"""
        return NotImplementedError()

    def delete_snapshot(self, snapshot):
        """Deletes an rbd snapshot"""
        return NotImplementedError()

    def local_path(self, volume):
        """Returns the path of the rbd volume."""
        # This is the same as the remote path
        # since qemu accesses it directly.
        return "rbd:%s/%s" % (self.configuration.rbd_pool, volume['name'])

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume"""

        host = '127.0.0.1'
        port = '3260'
        target_name = volume['name']
        lun = '9'

        loc = '%s:%s,1 %s %s' %(host, port, target_name, lun)

        return {'provider_location': loc}

    def remove_export(self, context, volume):
        """Removes an export for a logical volume"""
        pass

    def initialize_connection(self, volume, connector):
        LOG.debug("initialize_connection...")
        LOG.debug("initiator: %s" % connector['initiator'])
        LOG.debug("volume: %s" % volume)

        # TODO: import?
        TYPE_ISCSI = 5
        ACCESS_READ_WRITE = 2

        initiator = self.get_initiator(connector['initiator'])
        v = self._get_volume(volume['id'])  # TODO: probably wrong?

        i = client.initiator_grant(initiator,
                                   TYPE_ISCSI,
                                   v,
                                   ACCESS_READ_WRITE)

        if i is not None:
            LOG.error("%s" % i)
            raise LibSMSomethingBroke()  # TODO

        username = str(uuid.uuid1())[:8]  # TODO: replace w/ some other function
        password = str(uuid.uuid1())[:8]

        initator_to_adjust = self._get_initiator(initiator)

        self.lsmclient.iscsi_chap_auth(initiator_to_adjust,
                                       username,
                                       password,
                                       None,
                                       None)


        # TODO: will need to specify LUN information here...
        # TODO: lots
        return {
            'driver_volume_type': 'lsm',
            'data': {
                'name': '%s/%s' % (self.configuration.rbd_pool,
                                   volume['name']),
                'auth_enabled': (self.configuration.rbd_secret_uuid
                                 is not None),
                'auth_username': self.configuration.rbd_user,
                'secret_type': 'ceph',
                'secret_uuid': self.configuration.rbd_secret_uuid, }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def _parse_location(self, location):
        prefix = 'rbd://'
        if not location.startswith(prefix):
            reason = _('Not stored in rbd')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        pieces = map(urllib.unquote, location[len(prefix):].split('/'))
        if any(map(lambda p: p == '', pieces)):
            reason = _('Blank components')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        if len(pieces) != 4:
            reason = _('Not an rbd snapshot')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        return pieces

    def _get_fsid(self):
        stdout, _ = self._execute('ceph', 'fsid')
        return stdout.rstrip('\n')

    def _is_cloneable(self, image_location):
        try:
            fsid, pool, image, snapshot = self._parse_location(image_location)
        except exception.ImageUnacceptable:
            return False

        if self._get_fsid() != fsid:
            reason = _('%s is in a different ceph cluster') % image_location
            LOG.debug(reason)
            return False

        # check that we can read the image
        try:
            self._execute('rbd', 'info',
                          '--pool', pool,
                          '--image', image,
                          '--snap', snapshot)
        except exception.ProcessExecutionError:
            LOG.debug(_('Unable to read image %s') % image_location)
            return False

        return True

    def clone_image(self, volume, image_location):
        return NotImplementedError()
        #if image_location is None or not self._is_cloneable(image_location):
        #    return False
        #_, pool, image, snapshot = self._parse_location(image_location)
        #self._clone(volume, pool, image, snapshot)
        #self._resize(volume)
        #return True

    def _ensure_tmp_exists(self):
        tmp_dir = self.configuration.volume_tmp_dir
        if tmp_dir and not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        # TODO(jdurgin): replace with librbd
        # this is a temporary hack, since rewriting this driver
        # to use librbd would take too long
        self._ensure_tmp_exists()
        tmp_dir = self.configuration.volume_tmp_dir

        with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp:
            image_utils.fetch_to_raw(context, image_service, image_id,
                                     tmp.name)
            # import creates the image, so we must remove it first
            self._try_execute('rbd', 'rm',
                              '--pool', self.configuration.rbd_pool,
                              volume['name'])

            args = ['rbd', 'import',
                    '--pool', self.configuration.rbd_pool,
                    tmp.name, volume['name']]
            if self._supports_layering():
                args += ['--new-format']
            self._try_execute(*args)
        self._resize(volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        self._ensure_tmp_exists()

        tmp_dir = self.configuration.volume_tmp_dir or '/tmp'
        tmp_file = os.path.join(tmp_dir,
                                volume['name'] + '-' + image_meta['id'])
        with utils.remove_path_on_error(tmp_file):
            self._try_execute('rbd', 'export',
                              '--pool', self.configuration.rbd_pool,
                              volume['name'], tmp_file)
            image_utils.upload_volume(context, image_service,
                                      image_meta, tmp_file)
        os.unlink(tmp_file)
