from typing import Any, Optional

class CinderPersistentObject:
    def get_by_id(context, id, **kwargs) -> CinderPersistentObject: ...
    def create(self) -> None: ...
    def save(self) -> None: ...
    def get(self, field: Any, default: Optional[Any]) -> Any: ...
    def conditional_update(self, values, expected) -> Any: ...
    def refresh(self) -> Any: ...
    def update(self, values) -> Any: ...
    def obj_reset_changes(self) -> Any: ...
    def destroy(self) -> None: ...

    def assert_not_frozen(self) -> Any: ...
    def update_single_status_where(self, new_status, expected_status, filters) -> Any: ...
    def obj_as_admin() -> CinderPersistentObject: ...
    def _from_db_object(): ...
    def __getitem__(self, arg): ...
    def __setitem__(self, arg, value): ...

    def obj_attr_is_set(self): ...

    obj_context: Any

class Volume(CinderPersistentObject):
    def get_by_id(context, id) -> Volume: ...
    id: str
    project_id: str
    size: int
    encryption_key_id: str
    status: str
    volume_attachment: Any
    previous_status: str
    multiattach: str
    volume_type_id: str
    snapshots: Iterable[Any]
    host: str
    volume_type_id: str
    snapshot_id: str
    admin_metadata: dict
    migration_status: str
    volume_type: dict
    bootable: bool
    volume_admin_metadata: dict
    use_quota: bool
    name_id: str
    name: str
    source_volid: str
    provider_location: str
    availability_zone: str
    consistencygroup: Optional[ConsistencyGroup]

    model: Any

    def set_workers(*args): ...
    def admin_metadata_update(): ...
    def begin_attach(): ...
    def begin_detach(): ...

class Backup(CinderPersistentObject):
    def get_by_id(context, id) -> Backup: ...
    id: str
    status: str
    num_dependent_backups: int
    has_dependent_backups: bool
    container: str

class Snapshot(CinderPersistentObject):
    def get_by_id(context, id) -> Snapshot: ...
    def delete_metadata_key(context, key) -> None: ...
    id: str
    status: str
    metadata: dict
    volume_type_id: str
    volume: Volume
    provider_auth: str
    use_quota: bool
    volume_size: int

class VolumeType(CinderPersistentObject):
    id: str
    extra_specs: dict

class ServiceList():
    def get_all_by_topic(context, topic): ...
    def get_all(context, filters): ...

class SnapshotList(Iterable): ...
class VolumeList(Iterable): ...
class VolumeProperties(): ...

class VolumeAttachment(CinderPersistentObject):
    id: str
    attach_mode: str
    connection_info: dict
    volume_id: str

class VolumeAttachmentList():
    def get_all_by_host(context, host): ...
    def get_all_by_instance_uuid(context, uuid): ...

class BackupList():
    def get_all_by_host(context, host): ...

class Group(CinderPersistentObject):
    id: str
    status: str
    name: str
    volumes: Iterable
    replication_status: str

class Service(CinderPersistentObject):
    disabled: bool
    disabled_reason: str
    frozen: bool
    is_clustered: bool

class BackupDeviceInfo(): ...

class ConsistencyGroup():
    volume_type_id: str

class CGSnapshot(): ...
