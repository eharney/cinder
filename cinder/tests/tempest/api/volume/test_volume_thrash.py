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

from tempest.api.volume import base
from tempest.common import waiters
from tempest import config
from tempest.lib.common.utils import data_utils
from tempest.lib import decorators

from cinder.tests.tempest import cinder_clients

CONF = config.CONF


class VolumeThrashTest(base.BaseVolumeAdminTest):

    @classmethod
    def setup_clients(cls):
        cls._api_version = 2
        super(VolumeThrashTest, cls).setup_clients()

        manager = cinder_clients.Manager(cls.os_adm)

    @classmethod
    def skip_checks(cls):
        super(VolumeThrashTest, cls).skip_checks()
        pass

    @decorators.idempotent_id('a149a9cf-3761-43d7-b89f-bcb7b41d79c5')
    def test_create_delete_volumes(self):
        # Create volume type
        name = data_utils.rand_name("volume-type")
        volume_type = self.admin_volume_types_client.create_volume_type(
            name=name)['volume_type']

        num_volumes = 6
        volumes = []
        for i in range(0, num_volumes):
            # Create volumes in parallel
            vol_name = data_utils.rand_name("volume")
            volume_params = {'name': vol_name,
                             'volume_type': volume_type['id'],
                             'size': CONF.volume.volume_size,
                             'imageRef': CONF.compute.image_ref}

            volumes.append(self.admin_volume_client.create_volume(**volume_params)['volume'])

        for i in range(0, num_volumes):
            # Check all create requests
            waiters.wait_for_volume_resource_status(self.admin_volume_client,
                                                    volumes[i]['id'],
                                                    'available')

        # Clean up
        for i in range(0, num_volumes):
            self.admin_volume_client.delete_volume(volumes[i]['id'])
