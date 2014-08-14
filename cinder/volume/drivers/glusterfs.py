# Copyright (c) 2013 Red Hat, Inc.
# All Rights Reserved.
#
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

import errno
import os
import stat
import time

from oslo.config import cfg

from cinder.brick.remotefs import remotefs as remotefs_brick
from cinder import compute
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import fileutils
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder.openstack.common import units
from cinder import utils
from cinder.volume.drivers import remotefs as remotefs_drv

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('glusterfs_shares_config',
               default='/etc/cinder/glusterfs_shares',
               help='File with the list of available gluster shares'),
    cfg.BoolOpt('glusterfs_sparsed_volumes',
                default=True,
                help=('Create volumes as sparsed files which take no space.'
                      'If set to False volume is created as regular file.'
                      'In such case volume creation takes a lot of time.')),
    cfg.BoolOpt('glusterfs_qcow2_volumes',
                default=False,
                help=('Create volumes as QCOW2 files rather than raw files.')),
    cfg.StrOpt('glusterfs_mount_point_base',
               default='$state_path/mnt',
               help='Base dir containing mount points for gluster shares.'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)
CONF.import_opt('volume_name_template', 'cinder.db')


class GlusterfsDriver(remotefs_drv.RemoteFSSnapDriver):
    """Gluster based cinder driver. Creates file on Gluster share for using it
    as block device on hypervisor.

    Operations such as create/delete/extend volume/snapshot use locking on a
    per-process basis to prevent multiple threads from modifying qcow2 chains
    or the snapshot .info file simultaneously.
    """

    driver_volume_type = 'glusterfs'
    driver_prefix = 'glusterfs'
    volume_backend_name = 'GlusterFS'
    VERSION = '1.2.0'

    def __init__(self, execute=processutils.execute, *args, **kwargs):
        self._remotefsclient = None
        super(GlusterfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)
        self.base = getattr(self.configuration,
                            'glusterfs_mount_point_base',
                            CONF.glusterfs_mount_point_base)
        self._remotefsclient = remotefs_brick.RemoteFsClient(
            'glusterfs',
            execute,
            glusterfs_mount_point_base=self.base)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(GlusterfsDriver, self).do_setup(context)

        config = self.configuration.glusterfs_shares_config
        if not config:
            msg = (_("There's no Gluster config file configured (%s)") %
                   'glusterfs_shares_config')
            LOG.warn(msg)
            raise exception.GlusterfsException(msg)
        if not os.path.exists(config):
            msg = (_("Gluster config file at %(config)s doesn't exist") %
                   {'config': config})
            LOG.warn(msg)
            raise exception.GlusterfsException(msg)

        self.shares = {}

        try:
            self._execute('mount.glusterfs', check_exit_code=False)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise exception.GlusterfsException(
                    _('mount.glusterfs is not installed'))
            else:
                raise

        self._refresh_mounts()

    def _unmount_shares(self):
        self._load_shares_config(self.configuration.glusterfs_shares_config)
        for share in self.shares.keys():
            try:
                self._do_umount(True, share)
            except Exception as exc:
                LOG.warning(_('Exception during unmounting %s') % (exc))

    def check_for_setup_error(self):
        """Just to override parent behavior."""
        pass

    def _local_volume_dir(self, volume):
        hashed = self._get_hash_str(volume['provider_location'])
        path = '%s/%s' % (self.configuration.glusterfs_mount_point_base,
                          hashed)
        return path

    @utils.synchronized('glusterfs', external=False)
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""

        LOG.info(_('Cloning volume %(src)s to volume %(dst)s') %
                 {'src': src_vref['id'],
                  'dst': volume['id']})

        if src_vref['status'] != 'available':
            msg = _("Volume status must be 'available'.")
            raise exception.InvalidVolume(msg)

        volume_name = CONF.volume_name_template % volume['id']

        volume_info = {'provider_location': src_vref['provider_location'],
                       'size': src_vref['size'],
                       'id': volume['id'],
                       'name': volume_name,
                       'status': src_vref['status']}
        temp_snapshot = {'volume_name': volume_name,
                         'size': src_vref['size'],
                         'volume_size': src_vref['size'],
                         'name': 'clone-snap-%s' % src_vref['id'],
                         'volume_id': src_vref['id'],
                         'id': 'tmp-snap-%s' % src_vref['id'],
                         'volume': src_vref}
        self._create_snapshot(temp_snapshot)
        try:
            self._copy_volume_from_snapshot(temp_snapshot,
                                            volume_info,
                                            src_vref['size'])

        finally:
            self._delete_snapshot(temp_snapshot)

        return {'provider_location': src_vref['provider_location']}

    @utils.synchronized('glusterfs', external=False)
    def create_volume(self, volume):
        """Creates a volume."""

        self._ensure_shares_mounted()

        volume['provider_location'] = self._find_share(volume['size'])

        LOG.info(_('casted to %s') % volume['provider_location'])

        self._do_create_volume(volume)

        return {'provider_location': volume['provider_location']}

    @utils.synchronized('glusterfs', external=False)
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        Snapshot must not be the active snapshot. (offline)
        """

        if snapshot['status'] != 'available':
            msg = _('Snapshot status must be "available" to clone.')
            raise exception.InvalidSnapshot(msg)

        self._ensure_shares_mounted()

        volume['provider_location'] = self._find_share(volume['size'])

        self._do_create_volume(volume)

        self._copy_volume_from_snapshot(snapshot,
                                        volume,
                                        snapshot['volume_size'])

        return {'provider_location': volume['provider_location']}

    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size):
        """Copy data from snapshot to destination volume.

        This is done with a qemu-img convert to raw/qcow2 from the snapshot
        qcow2.
        """

        LOG.debug("snapshot: %(snap)s, volume: %(vol)s, "
                  "volume_size: %(size)s"
                  % {'snap': snapshot['id'],
                     'vol': volume['id'],
                     'size': volume_size})

        info_path = self._local_path_volume_info(snapshot['volume'])
        snap_info = self._read_info_file(info_path)
        vol_path = self._local_volume_dir(snapshot['volume'])
        forward_file = snap_info[snapshot['id']]
        forward_path = os.path.join(vol_path, forward_file)

        # Find the file which backs this file, which represents the point
        # when this snapshot was created.
        img_info = self._qemu_img_info(forward_path)
        path_to_snap_img = os.path.join(vol_path, img_info.backing_file)

        path_to_new_vol = self._local_path_volume(volume)

        LOG.debug("will copy from snapshot at %s" % path_to_snap_img)

        if self.configuration.glusterfs_qcow2_volumes:
            out_format = 'qcow2'
        else:
            out_format = 'raw'

        image_utils.convert_image(path_to_snap_img,
                                  path_to_new_vol,
                                  out_format)

        self._set_rw_permissions_for_all(path_to_new_vol)

    @utils.synchronized('glusterfs', external=False)
    def delete_volume(self, volume):
        """Deletes a logical volume."""
        super(GlusterFSDriver, self).delete_volume(volume)

    @utils.synchronized('glusterfs', external=False)
    def create_snapshot(self, snapshot):
        """Apply locking to the create snapshot operation."""

        return self._create_snapshot(snapshot)

    @utils.synchronized('glusterfs', external=False)
    def delete_snapshot(self, snapshot):
        """Apply locking to the delete snapshot operation."""
        self._delete_snapshot(snapshot)

    def ensure_export(self, ctx, volume):
        """Synchronously recreates an export for a logical volume."""

        self._ensure_share_mounted(volume['provider_location'])

    def create_export(self, ctx, volume):
        """Exports the volume."""
        pass

    def remove_export(self, ctx, volume):
        """Removes an export for a logical volume."""
        pass

    def validate_connector(self, connector):
        pass

    @utils.synchronized('glusterfs', external=False)
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""

        # Find active qcow2 file
        active_file = self.get_active_image_from_info(volume)
        path = '%s/%s/%s' % (self.configuration.glusterfs_mount_point_base,
                             self._get_hash_str(volume['provider_location']),
                             active_file)

        data = {'export': volume['provider_location'],
                'name': active_file}
        if volume['provider_location'] in self.shares:
            data['options'] = self.shares[volume['provider_location']]

        # Test file for raw vs. qcow2 format
        info = self._qemu_img_info(path)
        data['format'] = info.file_format
        if data['format'] not in ['raw', 'qcow2']:
            msg = _('%s must be a valid raw or qcow2 image.') % path
            raise exception.InvalidVolume(msg)

        return {
            'driver_volume_type': 'glusterfs',
            'data': data,
            'mount_point_base': self._get_mount_point_base()
        }

    @utils.synchronized('glusterfs', external=False)
    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""

        # If snapshots exist, flatten to a temporary image, and upload it

        active_file = self.get_active_image_from_info(volume)
        active_file_path = '%s/%s' % (self._local_volume_dir(volume),
                                      active_file)
        info = self._qemu_img_info(active_file_path)
        backing_file = info.backing_file
        if backing_file:
            snapshots_exist = True
        else:
            snapshots_exist = False

        root_file_fmt = info.file_format

        temp_path = None

        try:
            if snapshots_exist or (root_file_fmt != 'raw'):
                # Convert due to snapshots
                # or volume data not being stored in raw format
                #  (upload_volume assumes raw format input)
                temp_path = '%s/%s.temp_image.%s' % (
                    self._local_volume_dir(volume),
                    volume['id'],
                    image_meta['id'])

                image_utils.convert_image(active_file_path, temp_path, 'raw')
                upload_path = temp_path
            else:
                upload_path = active_file_path

            image_utils.upload_volume(context,
                                      image_service,
                                      image_meta,
                                      upload_path)
        finally:
            if temp_path is not None:
                self._execute('rm', '-f', temp_path)

    @utils.synchronized('glusterfs', external=False)
    def extend_volume(self, volume, size_gb):
        super(GlusterFSDriver, self)._extend_volume(volume, size_gb)

    def _do_create_volume(self, volume):
        """Create a volume on given glusterfs_share.

        :param volume: volume reference
        """

        volume_path = self.local_path(volume)
        volume_size = volume['size']

        LOG.debug("creating new volume at %s" % volume_path)

        if os.path.exists(volume_path):
            msg = _('file already exists at %s') % volume_path
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        if self.configuration.glusterfs_qcow2_volumes:
            self._create_qcow2_file(volume_path, volume_size)
        else:
            if self.configuration.glusterfs_sparsed_volumes:
                self._create_sparsed_file(volume_path, volume_size)
            else:
                self._create_regular_file(volume_path, volume_size)

        self._set_rw_permissions_for_all(volume_path)

    def _ensure_shares_mounted(self):
        """Mount all configured GlusterFS shares."""

        self._mounted_shares = []

        self._load_shares_config(self.configuration.glusterfs_shares_config)

        for share in self.shares.keys():
            try:
                self._ensure_share_mounted(share)
                self._mounted_shares.append(share)
            except Exception as exc:
                LOG.error(_('Exception during mounting %s') % (exc,))

        LOG.debug('Available shares: %s' % self._mounted_shares)

    def _ensure_share_mounted(self, glusterfs_share):
        """Mount GlusterFS share.
        :param glusterfs_share: string
        """
        mount_path = self._get_mount_point_for_share(glusterfs_share)
        self._mount_glusterfs(glusterfs_share, mount_path, ensure=True)

        # Ensure we can write to this share
        group_id = os.getegid()
        current_group_id = utils.get_file_gid(mount_path)
        current_mode = utils.get_file_mode(mount_path)

        if group_id != current_group_id:
            cmd = ['chgrp', group_id, mount_path]
            self._execute(*cmd, run_as_root=True)

        if not (current_mode & stat.S_IWGRP):
            cmd = ['chmod', 'g+w', mount_path]
            self._execute(*cmd, run_as_root=True)

        self._ensure_share_writable(mount_path)

    def _find_share(self, volume_size_for):
        """Choose GlusterFS share among available ones for given volume size.
        Current implementation looks for greatest capacity.
        :param volume_size_for: int size in GB
        """

        if not self._mounted_shares:
            raise exception.GlusterfsNoSharesMounted()

        greatest_size = 0
        greatest_share = None

        for glusterfs_share in self._mounted_shares:
            capacity = self._get_available_capacity(glusterfs_share)[0]
            if capacity > greatest_size:
                greatest_share = glusterfs_share
                greatest_size = capacity

        if volume_size_for * units.Gi > greatest_size:
            raise exception.GlusterfsNoSuitableShareFound(
                volume_size=volume_size_for)
        return greatest_share

    def _mount_glusterfs(self, glusterfs_share, mount_path, ensure=False):
        """Mount GlusterFS share to mount path."""
        # TODO(eharney): make this fs-agnostic and factor into remotefs
        self._execute('mkdir', '-p', mount_path)

        command = ['mount', '-t', 'glusterfs', glusterfs_share,
                   mount_path]
        if self.shares.get(glusterfs_share) is not None:
            command.extend(self.shares[glusterfs_share].split())

        self._do_mount(command, ensure, glusterfs_share)

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume.

        Allow a backup to occur only if no snapshots exist.
        Check both Cinder and the file on-disk.  The latter is only
        a safety mechanism to prevent further damage if the snapshot
        information is already inconsistent.
        """

        snapshots = self.db.snapshot_get_all_for_volume(context,
                                                        backup['volume_id'])
        snap_error_msg = _('Backup is not supported for GlusterFS '
                           'volumes with snapshots.')
        if len(snapshots) > 0:
            raise exception.InvalidVolume(snap_error_msg)

        volume = self.db.volume_get(context, backup['volume_id'])

        volume_dir = self._local_volume_dir(volume)
        active_file_path = os.path.join(
            volume_dir,
            self.get_active_image_from_info(volume))

        info = self._qemu_img_info(active_file_path)

        if info.backing_file is not None:
            msg = _('No snapshots found in database, but '
                    '%(path)s has backing file '
                    '%(backing_file)s!') % {'path': active_file_path,
                                            'backing_file': info.backing_file}
            LOG.error(msg)
            raise exception.InvalidVolume(snap_error_msg)

        if info.file_format != 'raw':
            msg = _('Backup is only supported for raw-formatted '
                    'GlusterFS volumes.')
            raise exception.InvalidVolume(msg)

        return super(GlusterfsDriver, self).backup_volume(
            context, backup, backup_service)
