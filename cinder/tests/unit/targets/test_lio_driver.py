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

import mock
from oslo_concurrency import processutils as putils
import six

from cinder import context
from cinder import exception
from cinder.tests import fixtures
import cinder.privileged
from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume.targets import lio


class TestLioAdmDriver(tf.TargetDriverFixture):

    def setUp(self):
        super(TestLioAdmDriver, self).setUp()

        self.useFixture(fixtures.PrivsepFixture())

        with mock.patch.object(lio.LioAdm, '_verify_rtstool'):
            self.target = lio.LioAdm(root_helper=utils.get_root_helper(),
                                     configuration=self.configuration)


    @mock.patch('cinder.privileged.target_lio.get_targets')
    @mock.patch.object(lio.LioAdm, '_execute', side_effect=lio.LioAdm._execute)
    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch('cinder.utils.execute')
    def test_get_target(self, mexecute, mpersist_cfg, mlock_exec, mock_get_targets):
        mock_get_targets.return_value = (self.test_vol, None)
        mexecute.return_value = (self.test_vol, None)
        self.assertEqual(self.test_vol, self.target._get_target(self.test_vol))
        self.assertFalse(mpersist_cfg.called)
        expected_args = ('cinder-rtstool', 'get-targets')
        #mlock_exec.assert_called_once_with(*expected_args, run_as_root=True)
        #mexecute.assert_called_once_with(*expected_args, run_as_root=True)

    def test_get_iscsi_target(self):
        ctxt = context.get_admin_context()
        expected = 0
        self.assertEqual(expected,
                         self.target._get_iscsi_target(ctxt,
                                                       self.testvol['id']))

    def test_get_target_and_lun(self):
        lun = 0
        iscsi_target = 0
        ctxt = context.get_admin_context()
        expected = (iscsi_target, lun)
        self.assertEqual(expected,
                         self.target._get_target_and_lun(ctxt, self.testvol))

    @mock.patch('cinder.privileged.target_lio.create')
    @mock.patch.object(lio.LioAdm, '_execute', side_effect=lio.LioAdm._execute)
    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch('cinder.utils.execute')
    @mock.patch.object(lio.LioAdm, '_get_target')
    def test_create_iscsi_target(self, mget_target, mexecute, mpersist_cfg,
                                 mlock_exec, mock_create):

        mget_target.return_value = 1
        # create_iscsi_target sends volume_name instead of volume_id on error
        self.assertEqual(
            1,
            self.target.create_iscsi_target(
                self.test_vol,
                1,
                0,
                self.fake_volumes_dir))
        mpersist_cfg.assert_called_once_with(self.VOLUME_NAME)
        #mexecute.assert_called_once_with(
        #    'cinder-rtstool',
        #    'create',
        #    self.fake_volumes_dir,
        #    self.test_vol,
        #    '',
        #    '',
        #    self.target.iscsi_protocol == 'iser',
        #    run_as_root=True)
        mock_create.assert_called_once_with(self.fake_volumes_dir,
                                            self.iscsi_target_prefix + self.VOLUME_NAME,
                                            '',
                                            '',
                                            False,
                                            portals_ips=None,
                                            portals_port=None)

    @mock.patch('cinder.privileged.target_lio.create')
    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch.object(lio.LioAdm, '_get_target', return_value=1)
    def test_create_iscsi_target_port_ip(self, mget_target, mpersist_cfg, mock_create):
        ip = '198.51.100.1'
        port = 3261

        self.assertEqual(
            1,
            self.target.create_iscsi_target(
                self.test_vol,
                1,
                0,
                self.fake_volumes_dir,
                **{'portals_port': port, 'portals_ips': [ip]}))

        expected_args = (
            'cinder-rtstool',
            'create',
            self.fake_volumes_dir,
            self.test_vol,
            '',
            '',
            self.target.iscsi_protocol == 'iser',
            '-p%s' % port,
            '-a' + ip)

        mock_create.assert_called_once_with(self.fake_volumes_dir,
                                            self.iscsi_target_prefix + self.VOLUME_NAME,
                                            '',
                                            '',
                                            False,
                                            portals_ips=['198.51.100.1'],
                                            portals_port=3261)

        mpersist_cfg.assert_called_once_with(self.VOLUME_NAME)

    @mock.patch('cinder.privileged.target_lio.create')
    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch.object(lio.LioAdm, '_get_target', return_value=1)
    def test_create_iscsi_target_port_ips(self, mget_target, mpersist_cfg, mock_create):
        test_vol = 'iqn.2010-10.org.openstack:' + self.VOLUME_NAME
        ips = ['192.0.2.1', '127.0.0.1']
        port = 3261

        self.assertEqual(
            1,
            self.target.create_iscsi_target(
                test_vol,
                1,
                0,
                self.fake_volumes_dir,
                **{'portals_port': port, 'portals_ips': ips}))

        expected_args = (
            'cinder-rtstool',
            'create',
            self.fake_volumes_dir,
            test_vol,
            '',
            '',
            self.target.iscsi_protocol == 'iser',
            '-p%s' % port,
            '-a' + ','.join(ips))

        mock_create.assert_called_once_with(self.fake_volumes_dir,
                                            self.iscsi_target_prefix + self.VOLUME_NAME,
                                            '',
                                            '',
                                            False,
                                            portals_ips=['192.0.2.1', '127.0.0.1'],
                                            portals_port=3261)
        mpersist_cfg.assert_called_once_with(self.VOLUME_NAME)

    @mock.patch('cinder.privileged.target_lio.create', side_effect=Exception)
    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch.object(lio.LioAdm, '_get_target')
    def test_create_iscsi_target_already_exists(self,
                                                mget_target,
                                                mpersist_cfg,
                                                mock_create):
        chap_auth = ('foo', 'bar')
        self.assertRaises(exception.ISCSITargetCreateFailed,
                          self.target.create_iscsi_target,
                          self.test_vol,
                          1,
                          0,
                          self.fake_volumes_dir,
                          chap_auth)
        self.assertFalse(mpersist_cfg.called)
        expected_args = ('cinder-rtstool', 'create', self.fake_volumes_dir,
                         self.test_vol, chap_auth[0], chap_auth[1], False)
        mock_create.assert_called_once_with(self.fake_volumes_dir,
                                            self.iscsi_target_prefix + self.VOLUME_NAME,
                                            chap_auth[0], chap_auth[1],
                                            False,
                                            portals_ips=None,
                                            portals_port=None)

    @mock.patch('cinder.privileged.target_lio.delete')
    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    def test_remove_iscsi_target(self, mpersist_cfg, mock_delete):
        # Test the normal case
        self.target.remove_iscsi_target(0,
                                        0,
                                        self.testvol['id'],
                                        self.testvol['name'])
        expected_args = ('cinder-rtstool', 'delete',
                         self.iscsi_target_prefix + self.testvol['name'])

        mpersist_cfg.assert_called_once_with(self.fake_volume_id)
        mock_delete.assert_called_once_with(self.iscsi_target_prefix + self.testvol['name'])

        # Test the failure case: putils.ProcessExecutionError
        mpersist_cfg.reset_mock()
        mock_delete.reset_mock()
        mock_delete.side_effect = Exception
        self.assertRaises(exception.ISCSITargetRemoveFailed,
                          self.target.remove_iscsi_target,
                          0,
                          0,
                          self.testvol['id'],
                          self.testvol['name'])
        mock_delete.assert_called_once_with(self.iscsi_target_prefix + self.testvol['name'])

        # Ensure there have been no calls to persist configuration
        self.assertFalse(mpersist_cfg.called)

    @mock.patch.object(lio.LioAdm, '_get_targets')
    @mock.patch.object(lio.LioAdm, '_execute', side_effect=lio.LioAdm._execute)
    @mock.patch('cinder.utils.execute')
    def test_ensure_export(self, mock_exec, mock_execute, mock_get_targets):

        ctxt = context.get_admin_context()
        mock_get_targets.return_value = None
        self.target.ensure_export(ctxt,
                                  self.testvol,
                                  self.fake_volumes_dir)

        expected_args = ('cinder-rtstool', 'restore')
        mock_exec.assert_called_once_with(*expected_args, run_as_root=True)

    @mock.patch.object(lio.LioAdm, '_get_targets')
    @mock.patch.object(lio.LioAdm, '_restore_configuration')
    def test_ensure_export_target_exist(self, mock_restore, mock_get_targets):

        ctxt = context.get_admin_context()
        mock_get_targets.return_value = 'target'
        self.target.ensure_export(ctxt,
                                  self.testvol,
                                  self.fake_volumes_dir)
        self.assertFalse(mock_restore.called)

    @mock.patch('cinder.privileged.target_lio.add_initiator')
    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch.object(lio.LioAdm, '_get_iscsi_properties')
    def test_initialize_connection(self, mock_get_iscsi, mpersist_cfg, mock_add_initiator):
        target_id = self.iscsi_target_prefix + 'volume-' + self.fake_volume_id
        connector = {'initiator': 'fake_init'}

        # Test the normal case
        mock_get_iscsi.return_value = 'foo bar'
        expected_return = {'driver_volume_type': 'iscsi',
                           'data': 'foo bar'}
        self.assertEqual(expected_return,
                         self.target.initialize_connection(self.testvol,
                                                           connector))

        expected_args = ('cinder-rtstool', 'add-initiator', target_id,
                         self.expected_iscsi_properties['auth_username'],
                         '2FE0CQ8J196R', connector['initiator'])

        mock_add_initiator.assert_called_once_with(target_id,
                                                   connector['initiator'],
                                                   self.expected_iscsi_properties['auth_username'],
                                                   '2FE0CQ8J196R')

        # Test the failure case: putils.ProcessExecutionError
        mpersist_cfg.reset_mock()
        mock_add_initiator.reset_mock()
        mock_add_initiator.side_effect = Exception
        self.assertRaises(exception.ISCSITargetAttachFailed,
                          self.target.initialize_connection,
                          self.testvol,
                          connector)

        mock_add_initiator.assert_called_once_with(target_id,
                                                   connector['initiator'],
                                                   self.expected_iscsi_properties['auth_username'],
                                                   '2FE0CQ8J196R')

        # Ensure there have been no calls to persist configuration
        self.assertFalse(mpersist_cfg.called)

    @mock.patch('cinder.privileged.target_lio.delete_initiator')
    @mock.patch.object(lio.LioAdm, '_execute', side_effect=lio.LioAdm._execute)
    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch('cinder.utils.execute')
    def test_terminate_connection(self, mock_execute, mpersist_cfg,
                                  mlock_exec, mock_target_lio):
        # TODO: rewrite these tests to work this way-- test calls to target_lio
        # Then we need other tests for inside of target_lio

        target_id = self.iscsi_target_prefix + 'volume-' + self.fake_volume_id

        connector = {'initiator': 'fake_init'}
        self.target.terminate_connection(self.testvol,
                                         connector)
        expected_args = (target_id, connector['initiator'])

        #mlock_exec.assert_called_once_with(*expected_args, run_as_root=True)
        #mock_execute.assert_called_once_with(*expected_args, run_as_root=True)
        mpersist_cfg.assert_called_once_with(self.fake_volume_id)
        mock_target_lio.assert_called_once_with(*expected_args)

    @mock.patch.object(lio.LioAdm, '_execute', side_effect=lio.LioAdm._execute)
    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch('cinder.utils.execute')
    def test_terminate_connection_no_prov_loc(self,
                                              mock_execute,
                                              mpersist_cfg,
                                              mlock_exec):
        """terminate_connection does nothing if provider_location is None"""

        connector = {'initiator': 'fake_init'}
        self.target.terminate_connection(self.testvol_no_prov_loc,
                                         connector)

        mlock_exec.assert_not_called()
        mock_execute.assert_not_called()
        mpersist_cfg.assert_not_called()

    @mock.patch('cinder.privileged.target_lio.delete_initiator', side_effect=Exception)
    @mock.patch.object(lio.LioAdm, '_execute', side_effect=lio.LioAdm._execute)
    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch('cinder.utils.execute')
    def test_terminate_connection_fail(self, mock_execute, mpersist_cfg,
                                       mlock_exec, mock_target_lio_di):

        target_id = self.iscsi_target_prefix + 'volume-' + self.fake_volume_id
        mock_execute.side_effect = putils.ProcessExecutionError
        connector = {'initiator': 'fake_init'}
        self.assertRaises(exception.ISCSITargetDetachFailed,
                          self.target.terminate_connection,
                          self.testvol,
                          connector)
        #mlock_exec.assert_called_once_with('cinder-rtstool',
        #                                   'delete-initiator', target_id,
        #                                   connector['initiator'],
        #                                   run_as_root=True)
        mock_target_lio_di.assert_called_once_with(target_id,
                                                   connector['initiator'])
        self.assertFalse(mpersist_cfg.called)

    def test_iscsi_protocol(self):
        self.assertEqual('iscsi', self.target.iscsi_protocol)

    @mock.patch.object(lio.LioAdm, '_get_target_and_lun', return_value=(1, 2))
    @mock.patch.object(lio.LioAdm, 'create_iscsi_target', return_value=3)
    @mock.patch.object(lio.LioAdm, '_get_target_chap_auth',
                       return_value=(mock.sentinel.user, mock.sentinel.pwd))
    def test_create_export(self, mock_chap, mock_create, mock_get_target):
        ctxt = context.get_admin_context()
        result = self.target.create_export(ctxt, self.testvol_2,
                                           self.fake_volumes_dir)

        loc = (u'%(ip)s:%(port)d,3 %(prefix)s%(name)s 2' %
               {'ip': self.configuration.target_ip_address,
                'port': self.configuration.target_port,
                'prefix': self.iscsi_target_prefix,
                'name': self.testvol_2['name']})

        expected_result = {
            'location': loc,
            'auth': 'CHAP %s %s' % (mock.sentinel.user, mock.sentinel.pwd),
        }

        self.assertEqual(expected_result, result)

        mock_create.assert_called_once_with(
            self.iscsi_target_prefix + self.testvol_2['name'],
            1,
            2,
            self.fake_volumes_dir,
            (mock.sentinel.user, mock.sentinel.pwd),
            portals_ips=[self.configuration.target_ip_address],
            portals_port=self.configuration.target_port)

