"""Level 1 (plan 5.2): a job is objects plus settings; slice() runs the whole pipeline in a worker process and returns a Result."""
import hashlib

import numpy as np

from . import worker


class Job:
    """objects with their transforms and per-object settings, and the settings of the print (Orca's option keys, values as strings).

        job = Job(settings={"sparse_infill_density": "30%"})
        job.add_object(vertices, faces, name="bracket", transform=T, settings={"wall_loops": "4"})
        result = job.slice(progress=print, cancel=event)
    """

    def __init__(self, settings=None, threads=None):
        self.settings = {str(k): str(v) for k, v in (settings or {}).items()}
        self.threads = threads
        self.objects = []

    def add_object(self, vertices, faces, name="object", transform=None, settings=None):
        """vertices (N, 3) in mm, faces (M, 3) indices into vertices; transform a 4x4 matrix (plate position and rotation), default identity.
        Raises ValueError, in words, for a mesh the engine could not take (empty, not finite, an index that points nowhere)."""
        v = np.asarray(vertices, dtype=np.float64)
        f = np.asarray(faces)
        if v.ndim != 2 or v.shape[1] != 3 or len(v) == 0:
            raise ValueError("The object %r has no vertices (expected an N x 3 array)." % name)
        if f.ndim != 2 or f.shape[1] != 3 or len(f) == 0:
            raise ValueError("The object %r has no triangles (expected an M x 3 array)." % name)
        if not np.issubdtype(f.dtype, np.integer):
            if np.any(f != np.floor(f)):
                raise ValueError("The object %r has face indices that are not whole numbers." % name)
        if not np.all(np.isfinite(v)):
            raise ValueError("The object %r has a vertex that is not a number (NaN or infinity)." % name)
        if f.min() < 0 or f.max() >= len(v):
            raise ValueError("The object %r has a triangle that points at a vertex that does not exist." % name)
        t = np.eye(4) if transform is None else np.asarray(transform, dtype=np.float64)
        if t.shape != (4, 4) or not np.all(np.isfinite(t)):
            raise ValueError("The transform of %r must be a 4 x 4 matrix of numbers." % name)
        self.objects.append({"name": str(name), "vertices": v, "faces": f.astype(np.int32), "transform": t,
                             "settings": {str(k): str(x) for k, x in (settings or {}).items()}})
        return len(self.objects) - 1

    def mesh_hashes(self):
        """A hash of each input mesh (for the reproducibility record)."""
        return [hashlib.sha256(o["vertices"].tobytes() + o["faces"].tobytes()).hexdigest() for o in self.objects]

    def slice(self, progress=None, cancel=None, timeout=None, until="gcode", **kw):
        """Runs the pipeline in a worker process.  See worker.run_job for progress, cancel, timeout and what is raised."""
        if not self.objects:
            raise ValueError("There is nothing to slice: add an object first.")
        import os
        threads = self.threads or max(1, (os.cpu_count() or 2) - 1)       # leave one core for the window
        return worker.run_job(self.objects, self.settings, threads, until, progress=progress, cancel=cancel, timeout=timeout, **kw)
