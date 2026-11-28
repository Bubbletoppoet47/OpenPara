"""What can go wrong, kept apart (plan 5.7): a setting that cannot work, a slice that failed, a cancel, a worker that died.

Every one is an Exception whose str() is a sentence a person can read; the attributes are for the program (for example to put the cursor on the
setting named by ConfigError.key)."""


class OrcaCoreError(Exception):
    """Base of everything this module raises on purpose."""


class ConfigError(OrcaCoreError):
    """Settings that cannot work together (Orca's Print::validate).  key is Orca's option key ('' when it is about the plate as a whole);
    object is the name of the object it concerns, or None."""
    def __init__(self, key, message, object=None):
        super().__init__(message)
        self.key, self.message, self.object = key, message, object


class SliceError(OrcaCoreError):
    """The slice failed for a reason in the model or the settings (Orca's SlicingError).  object is the name of the object that failed, or None."""
    def __init__(self, object, message):
        super().__init__(message)
        self.object, self.message = object, message


class SliceTimeout(SliceError):
    """The slice was stopped because it took longer than the time it was given."""


class Cancelled(OrcaCoreError):
    """The slice was cancelled by the caller."""


class WorkerCrashed(OrcaCoreError):
    """The worker process ended without giving a result: the engine crashed (or the system ended it, for example for lack of memory).
    OpenPara itself is not affected.  exit_code is the process's (negative on Linux for a signal), last_progress the last thing it reported,
    log the end of what it wrote to its log."""
    def __init__(self, exit_code, last_progress="", log=""):
        msg = "Slicing stopped: the slicing engine ended unexpectedly (exit code %s)" % exit_code
        if last_progress:
            msg += " while it was at: " + last_progress
        super().__init__(msg + ".")
        self.exit_code, self.last_progress, self.log = exit_code, last_progress, log


class EngineMissing(OrcaCoreError):
    """The compiled engine is not there (it is not built yet, or not downloaded)."""
