"""tennis-lab: one trunk, configurations per model."""

from tennislab.chain import access as _access

__version__ = "0.1.0"

# When the chain driver launches a stage it names an access log; the audit hook on file
# opens is installed here, before any stage module runs (decision RB14).
_access.install()
