from cinder.cmd import rtstool
from cinder import privileged


@privileged.default.entrypoint
def create(*args, **kwargs):
    return rtstool.create(args, *kwargs)
