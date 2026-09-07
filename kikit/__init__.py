
from . import _version
__version__ = _version.get_versions()['version'] + " (meteopress edition)"

# Work around SWIG/KiCad binding incompatibilities before anything touches pcbnew
from . import swig_compat  # noqa: F401
