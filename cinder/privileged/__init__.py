
from oslo_privsep import capabilities as c
from oslo_privsep import priv_context

default = priv_context.PrivContext(
    __name__,
    cfg_section='privsep_cinder',
    pypath=__name__ + '.default',
    capabilities=[c.CAP_SYS_ADMIN]
)
