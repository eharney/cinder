#!/usr/bin/env python

# Copyright 2012 - 2013 Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import os
import sys

import rtslib_fb

from cinder import i18n
from cinder.i18n import _

i18n.enable_lazy()


class RtstoolError(Exception):
    pass


class RtstoolImportError(RtstoolError):
    pass


def _lookup_target(target_iqn, initiator_iqn):
    try:
        rtsroot = rtslib_fb.root.RTSRoot()
    except rtslib_fb.utils.RTSLibError:
        print(_('Ensure that configfs is mounted at /sys/kernel/config.'))
        raise

    # Look for the target
    for t in rtsroot.targets:
        if t.wwn == target_iqn:
            return t
    raise RtstoolError(_('Could not find target %s') % target_iqn)


def get_targets():
    rtsroot = rtslib_fb.root.RTSRoot()
    targets = []
    for x in rtsroot.targets:
        targets.append(x.wwn)
    return targets


def delete(iqn):
    rtsroot = rtslib_fb.root.RTSRoot()
    for x in rtsroot.targets:
        if x.wwn == iqn:
            x.delete()
            break

    for x in rtsroot.storage_objects:
        if x.name == iqn:
            x.delete()
            break


def verify_rtslib():
    for member in ['BlockStorageObject', 'FabricModule', 'LUN',
                   'MappedLUN', 'NetworkPortal', 'NodeACL', 'root',
                   'Target', 'TPG']:
        if not hasattr(rtslib_fb, member):
            raise RtstoolImportError(_("rtslib_fb is missing member %s: You "
                                       "may need a newer python-rtslib-fb.") %
                                     member)


def usage():
    print("Usage:")
    print(sys.argv[0] +
          " add-initiator [target_iqn] [userid] [password] [initiator_iqn]")
    print(sys.argv[0] +
          " delete-initiator [target_iqn] [initiator_iqn]")
    print(sys.argv[0] + " get-targets")
    print(sys.argv[0] + " delete [iqn]")
    print(sys.argv[0] + " verify")
    print(sys.argv[0] + " save [path_to_file]")
    sys.exit(1)


def save_to_file(destination_file):
    rtsroot = rtslib_fb.root.RTSRoot()
    try:
        # If default destination use rtslib default save file
        if not destination_file:
            destination_file = rtslib_fb.root.default_save_file
            path_to_file = os.path.dirname(destination_file)

            # NOTE(geguileo): With default file we ensure path exists and
            # create it if doesn't.
            # Cinder's LIO target helper runs this as root, so it will have no
            # problem creating directory /etc/target.
            # If run manually from the command line without being root you will
            # get an error, same as when creating and removing targets.
            if not os.path.exists(path_to_file):
                os.makedirs(path_to_file, 0o755)

    except OSError as exc:
        raise RtstoolError(_('targetcli not installed and could not create '
                             'default directory (%(default_path)s): %(exc)s') %
                           {'default_path': path_to_file, 'exc': exc})
    try:
        rtsroot.save_to_file(destination_file)
    except (OSError, IOError) as exc:
        raise RtstoolError(_('Could not save configuration to %(file_path)s: '
                             '%(exc)s') %
                           {'file_path': destination_file, 'exc': exc})


def restore_from_file(configuration_file):
    rtsroot = rtslib_fb.root.RTSRoot()
    # If configuration file is None, use rtslib default save file.
    if not configuration_file:
        configuration_file = rtslib_fb.root.default_save_file

    try:
        rtsroot.restore_from_file(configuration_file)
    except (OSError, IOError) as exc:
        raise RtstoolError(_('Could not restore configuration file '
                             '%(file_path)s: %(exc)s'),
                           {'file_path': configuration_file, 'exc': exc})


def parse_optional_create(argv):
    optional_args = {}

    for arg in argv:
        if arg.startswith('-a'):
            ips = [ip for ip in arg[2:].split(',') if ip]
            if not ips:
                usage()
            optional_args['portals_ips'] = ips
        elif arg.startswith('-p'):
            try:
                optional_args['portals_port'] = int(arg[2:])
            except ValueError:
                usage()
        else:
            optional_args['initiator_iqns'] = arg
    return optional_args


def main(argv=None):
    if argv is None:
        argv = sys.argv

    if len(argv) < 2:
        usage()

    if argv[1] == 'get-targets':
        targets = get_targets()
        for t in targets:
            print(t)

    elif argv[1] == 'delete':
        if len(argv) < 3:
            usage()

        iqn = argv[2]
        delete(iqn)

    elif argv[1] == 'verify':
        # This is used to verify that this script can be called by cinder,
        # and that rtslib_fb is new enough to work.
        verify_rtslib()
        return 0

    elif argv[1] == 'save':
        if len(argv) > 3:
            usage()

        destination_file = argv[2] if len(argv) > 2 else None
        save_to_file(destination_file)
        return 0

    elif argv[1] == 'restore':
        if len(argv) > 3:
            usage()

        configuration_file = argv[2] if len(argv) > 2 else None
        restore_from_file(configuration_file)
        return 0

    else:
        usage()

    return 0
