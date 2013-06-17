"""
libstoragemgmt volume driver
Requires libstoragemgmt 0.0.20 ?
"""

import json
import lsm
import os
import pprint
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
    cfg.StrOpt('lsm_uri',
               default='targetd://admin@192.168.122.169',  # TODO: change default
               help='...'),
    cfg.StrOpt('lsm_pool_name',
               default = 'vg-targetd',  # TODO: change default
               help='...'),
    cfg.StrOpt('lsm_user',
               default=None,
               help='the RADOS client name for accessing rbd volumes'),
    cfg.StrOpt('lsm_password',
               default=None,
               help='...'),
    cfg.StrOpt('lsm_target_iqn',
               default = 'iqn.2003-01.org.example.eric:1234',  # TODO: change default
               help='...'),
    cfg.StrOpt('lsm_target_portal',
               default = '192.168.122.169:3260',  # TODO: change default
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

        self.lsmclient = lsm.Client(self.configuration.lsm_uri, 'targetd')  # TODO: config
        self._test_lsm()

        self.pool_name = self.configuration.lsm_pool_name  # TODO: remove

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
        LOG.debug("creating cloned volume... dest: %s src: %s" % (volume, src_vref))
        pool = self._get_pool(self.pool_name)
        source_volume = self._get_volume_by_name(src_vref['name'])

        LOG.debug("replicate time...")

        # TODO: use REPLICATE_CLONE when supported, COPY but only offline when not

        (j,v) = self.lsmclient.volume_replicate(pool,
                                                lsm.Volume.REPLICATE_CLONE,
                                                source_volume,
                                                volume['name'])

        if src_vref.status != 'available':
           LOG.error("source volume status is %s" % volume.status)
           raise VolumeIsNotAvailable()  # TODO

        try:
            # TODO: may only work if volume is offline -- need to check for this
            (j,v) = self.lsmclient.volume_replicate(pool,
                                                    lsm.Volume.REPLICATE_COPY,
                                                    source_volume,
                                                    volume['name'])
        except Exception as e:
            LOG.error("replicate exception: %s" % e)
            raise(e)

        # TODO: what else?

    def _get_pool(self, pool_name):
        for p in self.lsmclient.pools():
            if p.name == pool_name:
                return p

        LOG.error("couldn't find pool with name %s" % pool_name)

        raise exception.LibSMPoolNotFound(pool_name)

    def _get_initiator(self, initiator_name):
        for i in self.lsmclient.initiators():
            if i.id == initiator_name:
                return i
        LOG.error("Couldn't find initiator %s" % initiator_name)
        LOG.error("initiators: %s" % self.lsmclient.initiators())
        raise exception.LibSMInitiatorNotFound(initiator_name)

    def _get_volume(self, volume_id):
        for v in self.lsmclient.volumes():
            LOG.debug("looking at vol %s" % v.id)
            if v.id == volume_id:
                return v

        LOG.error("Couldn't find volume %s" % volume_id)
        #LOG.error("volumes: %s" % self.lsmclient.volumes())
        raise exception.LibSMVolumeNotFound(volume_id)

    def _get_volume_by_name(self, volume_name):
         for v in self.lsmclient.volumes():
             LOG.debug("looking at vol %s" % v.name)
             if v.name == volume_name:
                 return v

         LOG.error("failed to find volume with name %s" % volume_name)

         raise exception.LibSMVolumeNotFound(volume_name)

    def _get_snapshot_by_name(self, snapshot_name):
         raise NotImplementedError()
         for s in self.lsmclient.snapshots():   # TODO FIXME: doesn't work.  Where is the snapshot data?
             if s.name == snapshot_name:
                 return s

         LOG.error("failed to find snapshot with name %s" % snapshot_name)

         raise exception.LibSMSnapshotNotFound(snapshot_name)

    def create_volume(self, volume):
        """Creates a logical volume."""
        self._test_lsm()

        LOG.debug("creating volume... name: %s, size: %d",
                  volume['name'],
                  volume['size'])

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


    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self._clone(volume, self.configuration.rbd_pool,
                    snapshot['volume_name'], snapshot['name'])
        if int(volume['size']):
            self._resize(volume)

    def delete_volume(self, volume):
        """Deletes a logical volume."""

	try:
            volume_to_delete = self._get_volume_by_name(volume['name'])
        except exception.LibSMVolumeNotFound:
            LOG.error("volume %s not found" % volume['name'])
            return

        #if volume_to_delete is None:
        #    LOG.error("volume %s not found" % volume['name'])
        #    raise exception.LibSMVolumeNotFound(volume['name'])  # TODO

        # unexport first
        for initiator in self.lsmclient.initiators_granted_to_volume(volume_to_delete):
            LOG.debug("removing initiator %s from volume %s" % (initiator.name, volume_to_delete))
            self.lsmclient.initiator_revoke(initiator, volume_to_delete)


        self.lsmclient.volume_delete(volume_to_delete)
        
    def create_snapshot(self, snapshot):
        """Creates a snapshot"""
        LOG.debug("creating snapshot... snapshot: %s" % snapshot)
        LOG.debug("creating snapshot... volume id: %s" % snapshot.volume_id)
        pool = self._get_pool(self.pool_name)
        volume = self._get_volume_by_name('volume-%s' % snapshot.volume_id)
        LOG.debug("creating snapshot... found volume: %s" % volume)

	snap_id = None

        try:
            # TODO: returns (j, v)
            (j, v) = self.lsmclient.volume_replicate(pool,
                                                     lsm.Volume.REPLICATE_SNAPSHOT,
                                                     volume,
                                                     'snapshot-%s' % snapshot.id)

            if j is not None:
                LOG.error("unexpected job created")
                raise LibSMSomethingBroke("implement async snaps") # TODO

            snap_id = v.id
        except lsm.LsmError as e:
            LOG.error("snapshot replicate LsmError: %s" % e)
            if e.code ==  lsm.ErrorNumber.NO_SUPPORT:  # 153
                LOG.warn("not supported... try other method")
                # TODO: fall back to block copy if volume is not online
            raise(e)
        except Exception as e:
            LOG.error("snapshot replicate exception: %s" % e)
            raise(e)

        if snap_id is not None:
            # TODO: return what?
            return snap_id

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot"""
        # Look for snapshots named snapshot-<id>, then
        # volumes named snapshot-<id>

        s = None

        try:
            s = self._get_snapshot_by_name('snapshot-%s' % snapshot.id)
        except exception.LibSMSnapshotNotFound:
            # look for volume
            pass

        if s is not None:
            s.deletesomehow()  # TODO

        try:
            v = self._get_volume_by_name('snapshot-%s' % snapshot.id)
        except exception.LibSMVolumeNotFound:
            raise exception.LibSMSnapshotNotFound(snapshot.id)

        if v is not None:
            self.lsmclient.volume_delete(v)

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

        #initiator = self._get_initiator(connector['initiator'])
        v = self._get_volume_by_name('volume-%s' % volume['id'])  # TODO: verify

        i = self.lsmclient.initiator_grant(connector['initiator'],
                                           lsm.data.Initiator.TYPE_ISCSI,
                                           v,
                                           lsm.Volume.ACCESS_READ_WRITE)

        if i is not None:
            LOG.error("%s" % i)
            raise LibSMSomethingBroke()  # TODO

        username = utils.generate_username(8)
        password = utils.generate_password(8)

        initiator_to_adjust = self._get_initiator(connector['initiator'])

        self.lsmclient.iscsi_chap_auth(initiator_to_adjust,
                                       username,
                                       password,
                                       None,
                                       None)

        initiator = self._get_initiator(connector['initiator'])
        volume = self._get_volume_by_name('volume-%s' % volume['id'])

        LOG.debug("initiator: %s" % initiator)
        LOG.debug("volume: %s" % volume)


        # TODO: will need to specify LUN information here...
        # TODO: lots
        return {
            'driver_volume_type': 'iscsi',
            'data': {
                'name': '%s/%s' % ('fixme',   # TODO
                                   volume),
                'auth_enabled': 'fixme',
                'auth_username': 'username-fixme',
                'secret_type': 'fixme',
                'secret_uuid': 'fixme',
                'target_iqn': self.configuration.lsm_target_iqn,  # comes from targetd.yaml TODO: config
                'target_portal': self.configuration.lsm_target_portal # TODO: config
             }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass

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
