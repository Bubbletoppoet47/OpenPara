"""The backend that runs the compiled engine (the default of the worker, plan 5.1).

It runs inside the worker process: it writes the settings of the job to a file, hands the meshes and the file to the compiled module
(`_orca_core.slice`), and turns what comes back, or what goes wrong, into this package's own types and errors.  Cancelling is the file
`cancel` in the job folder (the compiled module watches it), progress is called from the engine's own status."""
import hashlib
import json
import os
import re

import numpy as np

from . import errors

_SEP = "\x1f"


def _core():
    try:
        from . import _orca_core                                  # the compiled part, built from engines/orca_core
    except ImportError:
        build = os.environ.get("ORCA_CORE_BUILD_DIR")             # a build folder (the tests, and people working on the engine)
        if build:
            import sys
            if build not in sys.path:
                sys.path.insert(0, build)
            try:
                import _orca_core
                return _orca_core
            except ImportError:
                pass
        raise errors.EngineMissing("The slicing engine is not built into this copy of OpenPara yet.") from None
    return _orca_core


def resources_dir():
    """Where Orca's small resource tables are (nozzle_info.json and others); the environment variable ORCA_CORE_RESOURCES, or `resources`
    next to this package, or nothing."""
    env = os.environ.get("ORCA_CORE_RESOURCES")
    if env and os.path.isdir(env):
        return env
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
    return here if os.path.isdir(here) else ""


def engine_version():
    """{'orca_version', 'orca_commit'} of the compiled engine."""
    return dict(_core().engine_version())


def _unpack(text):
    parts = str(text).split(_SEP, 2)
    return parts if len(parts) == 3 else ["", "", str(text)]


_INVALID = re.compile(r"Invalid value provided for parameter ([A-Za-z0-9_]+): (.*)", re.S)


def _plain_config_message(key, msg):
    """Orca's own wording for a value it cannot read ("Invalid value provided for parameter wall_loops: abc") as a sentence with the key apart."""
    m = _INVALID.search(msg)
    if m:
        return m.group(1), 'The value "%s" cannot be used for the setting "%s".' % (m.group(2).strip(), m.group(1))
    return key, msg


def run(job, folder, progress, is_cancelled):
    core = _core()
    settings_file = os.path.join(folder, "settings.json")
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(job["settings"], f)
    gcode = os.path.join(folder, "slice.gcode")
    objects = [{"name": o["name"], "vertices": np.ascontiguousarray(o["vertices"], dtype=np.float64),
                "faces": np.ascontiguousarray(o["faces"], dtype=np.int32), "transform": np.ascontiguousarray(o["transform"], dtype=np.float64),
                "settings": o.get("settings") or {}, "drop_to_bed": True} for o in job["objects"]]
    best = [0.0]

    def monotone(percent, message):
        """Orca's own percentages go back a little between its steps (71 then 70); a progress bar must not."""
        best[0] = max(best[0], float(percent))
        progress(best[0], message)

    try:
        out = core.slice(objects, settings_file, gcode, int(job.get("threads") or 1), job.get("until") or "gcode", resources_dir(),
                         os.path.join(folder, "cancel"), monotone)
    except core.Cancelled as e:
        raise errors.Cancelled(str(e)) from None
    except core.ConfigError as e:
        key, obj, msg = _unpack(e)
        key, msg = _plain_config_message(key, msg)
        raise errors.ConfigError(key, msg, obj or None) from None
    except core.SliceError as e:
        key, obj, msg = _unpack(e)
        raise errors.SliceError(obj or None, msg) from None
    rec = dict(out["record"])
    rec["module_version"] = _module_version()
    rec["bundle_version"] = job.get("bundle_version")
    rec["mesh_hashes"] = [hashlib.sha256(np.asarray(o["vertices"], dtype=np.float64).tobytes() + np.asarray(o["faces"], dtype=np.int32).tobytes()).hexdigest()
                          for o in job["objects"]]
    out["record"] = rec
    progress(100.0, "Done")
    return out


def _module_version():
    from . import __version__
    return __version__
