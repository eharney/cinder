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
from cinder import privileged

import rtslib_fb

LOG = logging.getLogger(__name__)


@privileged.default.entrypoint
def get_targets():
    return rtstool.get_targets()


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
