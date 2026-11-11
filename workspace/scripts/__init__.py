"""Isobar: CIM platform model, package-level evaluation and mapping search (see docs/)."""
# scripts.utils runs CiMLoop / Timeloop and needs the container stack (pytimeloop).
# On a host without it the attribute is set to None, so `from scripts import utils`
# yields None and the pure-Python modules (evaluation, search, exports) import and
# run on the host; only the CiMLoop measurements need the container.
try:
    from . import utils
except ImportError:
    utils = None
