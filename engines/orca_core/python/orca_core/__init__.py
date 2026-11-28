"""orca_core: Orca Slicer's slicing engine for OpenPara.

The engine itself is the compiled module _orca_core (engines/orca_core, built from Orca Slicer, AGPL-3.0).  This package is the part around
it, in Python: the result tables, the errors, and the worker process that keeps a crash in the engine from taking OpenPara with it.
Importing this package never needs the compiled engine; running a slice does (errors.EngineMissing says so in words)."""
from .errors import (OrcaCoreError, ConfigError, SliceError, SliceTimeout, Cancelled, WorkerCrashed, EngineMissing)
from .results import Paths, Moves, Estimate, SliceWarning, Result, PATH_COLUMNS
from .roles import ROLES, role_name, role_id
from .job import Job

__version__ = "0.0.1"
