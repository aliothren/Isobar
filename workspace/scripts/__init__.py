# The notebook/diagram helpers pull in the container-only stack (svgutils,
# IPython, matplotlib, timeloop). Import them lazily so the pure-python modules
# under scripts/ (geometry, write model, tests) stay importable on the host too.
try:
    from . import notebook_utils
    from . import utils
    from . import plots
except ImportError:                        # host / minimal env
    notebook_utils = utils = plots = None