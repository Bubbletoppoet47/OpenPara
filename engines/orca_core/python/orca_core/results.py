"""What a slice gives back (plan 5.3): the printed paths, the moves read back from the G-code, the estimate, the warnings, the record.

All of it is numpy arrays and plain Python values, copied out of the engine, so a result can be kept, saved, sent between processes and used
after the slice is gone.  Units are Orca's: millimetres, seconds, degrees Celsius, grams; plate coordinates.
"""
import json
import os
import shutil
from dataclasses import dataclass, field, asdict

import numpy as np

from .roles import ROLES, role_name, role_id

# per path: name -> (dtype, default).  `points` and `start` are the polylines themselves; `layer_z` is per layer, not per path.
PATH_COLUMNS = {
    "role": (np.uint8, 0),            # number in roles.ROLES
    "width": (np.float32, 0.0),       # extrusion width, mm
    "height": (np.float32, 0.0),      # layer height, mm
    "mm3_per_mm": (np.float32, 0.0),  # plastic volume per millimetre of travel
    "layer": (np.int32, 0),           # layer index; layer_z[layer] is its height
    "object": (np.int16, 0),
    "instance": (np.int16, 0),
    "region": (np.int16, 0),
    "extruder": (np.int8, 0),
    "order": (np.int32, None),        # position in the print sequence (default: the row number)
    "overhang": (np.float32, 0.0),
    "curve": (np.int8, 0),
    "z_contoured": (np.bool_, False),
}
REQUIRED_PATH_COLUMNS = ("role", "width", "height", "mm3_per_mm", "layer", "object")


class Paths:
    """Every printed line, one row per extrusion path.

    points  (N, 3) float32   the 3D polylines of all paths, one after the other
    start   (M + 1,) int64   path i is points[start[i]:start[i + 1]]
    layer_z (L,) float32     the top height of each layer
    and one array of length M for each name in PATH_COLUMNS (see there)."""

    def __init__(self, points, start, layer_z, columns):
        self.points = np.ascontiguousarray(points, dtype=np.float32).reshape(-1, 3)
        self.start = np.ascontiguousarray(start, dtype=np.int64)
        self.layer_z = np.ascontiguousarray(layer_z, dtype=np.float32).reshape(-1)
        self.columns = {k: np.ascontiguousarray(columns[k], dtype=PATH_COLUMNS[k][0]).reshape(-1) for k in columns}
        self.validate()

    # ---- building and checking
    @classmethod
    def from_columns(cls, points, start, layer_z, **columns):
        """Fills the columns that are not given with their defaults (order = the row number, the rest zero)."""
        start = np.asarray(start, dtype=np.int64)
        m = len(start) - 1
        unknown = set(columns) - set(PATH_COLUMNS)
        if unknown:
            raise ValueError("unknown path columns: %s" % ", ".join(sorted(unknown)))
        missing = [k for k in REQUIRED_PATH_COLUMNS if k not in columns]
        if missing:
            raise ValueError("path columns missing: %s" % ", ".join(missing))
        full = dict(columns)
        for k, (dt, default) in PATH_COLUMNS.items():
            if k not in full:
                full[k] = np.arange(m, dtype=dt) if default is None else np.full(m, default, dtype=dt)
        return cls(points, start, layer_z, full)

    @classmethod
    def empty(cls):
        return cls.from_columns(np.zeros((0, 3)), [0], [], **{k: [] for k in REQUIRED_PATH_COLUMNS})

    def validate(self):
        m = len(self.start) - 1
        if m < 0 or self.start[0] != 0 or np.any(np.diff(self.start) < 0) or self.start[-1] != len(self.points):
            raise ValueError("paths: `start` must begin at 0, never go down, and end at the number of points")
        for k in PATH_COLUMNS:
            if k not in self.columns:
                raise ValueError("paths: column %r is missing" % k)
            if len(self.columns[k]) != m:
                raise ValueError("paths: column %r has %d rows, expected %d" % (k, len(self.columns[k]), m))
        if m and self.columns["role"].max() >= len(ROLES):
            raise ValueError("paths: a role number is not one of Orca's %d roles" % len(ROLES))
        if m and len(self.layer_z) and (self.columns["layer"].min() < 0 or self.columns["layer"].max() >= len(self.layer_z)):
            raise ValueError("paths: a layer index is outside layer_z")

    # ---- reading
    def __len__(self):
        return len(self.start) - 1

    def __getattr__(self, name):                 # paths.role, paths.width ...
        cols = self.__dict__.get("columns")
        if cols is not None and name in cols:
            return cols[name]
        raise AttributeError(name)

    @property
    def n_layers(self):
        return len(self.layer_z)

    def path(self, i):
        """The points of path i, (n, 3) (a view, not a copy)."""
        return self.points[self.start[i]:self.start[i + 1]]

    def lengths(self):
        """Length of every path in mm, (M,) float64."""
        m = len(self)
        out = np.zeros(m)
        if len(self.points) < 2 or m == 0:
            return out
        d = np.linalg.norm(self.points[1:].astype(np.float64) - self.points[:-1].astype(np.float64), axis=1)
        cs = np.concatenate([[0.0], np.cumsum(d)])
        n = np.diff(self.start)
        ok = n >= 1
        out[ok] = cs[self.start[1:][ok] - 1] - cs[self.start[:-1][ok]]
        return out

    def volumes(self):
        """Plastic volume of every path in mm3 (length times mm3_per_mm), (M,) float64."""
        return self.lengths() * self.columns["mm3_per_mm"].astype(np.float64)

    def by_role(self):
        """{role name: (length in mm, volume in mm3)} for the roles that occur."""
        ln, vol, rl = self.lengths(), self.volumes(), self.columns["role"]
        return {role_name(r): (float(ln[rl == r].sum()), float(vol[rl == r].sum())) for r in np.unique(rl)}

    # ---- parts of it (copies)
    def select(self, which):
        """A new Paths with the paths in `which` (a boolean mask of length M or an array of path numbers), in the order given."""
        which = np.asarray(which)
        idx = np.flatnonzero(which) if which.dtype == np.bool_ else which.astype(np.int64)
        counts = self.start[idx + 1] - self.start[idx]
        new_start = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
        total = int(new_start[-1])
        gather = np.repeat(self.start[idx] - new_start[:-1], counts) + np.arange(total, dtype=np.int64)
        return Paths(self.points[gather], new_start, self.layer_z, {k: v[idx] for k, v in self.columns.items()})

    def layer_slice(self, layer):
        """The paths of one layer."""
        return self.select(self.columns["layer"] == layer)

    def object_slice(self, obj):
        """The paths of one object (all its copies)."""
        return self.select(self.columns["object"] == obj)

    def role_slice(self, *roles):
        """The paths of the given roles (names or numbers)."""
        ids = [role_id(r) if isinstance(r, str) else int(r) for r in roles]
        return self.select(np.isin(self.columns["role"], ids))

    # ---- files
    def to_arrays(self):
        d = {"points": self.points, "start": self.start, "layer_z": self.layer_z}
        d.update({"col_" + k: v for k, v in self.columns.items()})
        return d

    @classmethod
    def from_arrays(cls, d):
        return cls(d["points"], d["start"], d["layer_z"], {k: d["col_" + k] for k in PATH_COLUMNS})


class Moves:
    """The G-code read back, one row per move (what the printer will do).

    position (N, 3) float32 is required, and `role` (uint8, numbers in roles.ROLES), `feedrate` (mm/s) and `time` (s from the start of the print)
    are what the analysis reads; any other column of length N the engine gives (width, height, mm3_per_mm, fan, temperature, extruder,
    acceleration ...) is kept under its name."""

    REQUIRED = ("position",)

    def __init__(self, **columns):
        for k in self.REQUIRED:
            if k not in columns:
                raise ValueError("moves: column %r is missing" % k)
        pos = np.ascontiguousarray(columns.pop("position"), dtype=np.float32).reshape(-1, 3)
        self.columns = {"position": pos}
        for k, v in columns.items():
            a = np.ascontiguousarray(v)
            if a.shape[:1] != (len(pos),):
                raise ValueError("moves: column %r has %d rows, expected %d" % (k, a.shape[0] if a.ndim else 1, len(pos)))
            self.columns[k] = a

    def __len__(self):
        return len(self.columns["position"])

    def __getitem__(self, name):
        return self.columns[name]

    def __contains__(self, name):
        return name in self.columns

    def to_arrays(self):
        return dict(self.columns)

    @classmethod
    def from_arrays(cls, d):
        return cls(**{k: d[k] for k in d})


@dataclass
class Estimate:
    """Time and filament as Orca's own estimate gives them."""
    time_normal_s: float = 0.0
    time_silent_s: float = 0.0
    filament_mm: list = field(default_factory=list)        # per filament (extruder)
    filament_mm3: list = field(default_factory=list)
    filament_g: list = field(default_factory=list)
    cost: float = 0.0
    toolchanges: int = 0
    time_by_role_s: dict = field(default_factory=dict)     # role name -> seconds

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class SliceWarning:
    """Something Orca would have warned about.  level is 'tip', 'warning' or 'error'."""
    level: str
    message: str
    code: int = 0
    params: list = field(default_factory=list)
    object: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class Result:
    """paths, moves, estimate, warnings and record of one slice, and the G-code file.

    record is the reproducibility record (plan 5.8): orca_version, orca_commit, module_version, bundle_version, the fully resolved settings
    (`settings`), a hash of each input mesh (`mesh_hashes`) and the thread count."""

    def __init__(self, gcode_path, paths, moves, estimate, warnings, record):
        self.gcode_path = gcode_path
        self.paths = paths
        self.moves = moves
        self.estimate = estimate
        self.warnings = list(warnings)
        self.record = dict(record)

    def save(self, folder):
        """Writes the whole result to a folder (and a copy of the G-code), which Result.load reads back."""
        os.makedirs(folder, exist_ok=True)
        np.savez(os.path.join(folder, "paths.npz"), **self.paths.to_arrays())
        np.savez(os.path.join(folder, "moves.npz"), **self.moves.to_arrays())
        gname = ""
        if self.gcode_path and os.path.isfile(self.gcode_path):
            gname = os.path.basename(self.gcode_path)
            dst = os.path.join(folder, gname)
            if os.path.abspath(dst) != os.path.abspath(self.gcode_path):
                shutil.copyfile(self.gcode_path, dst)
        meta = {"gcode": gname, "estimate": self.estimate.to_dict(), "warnings": [w.to_dict() for w in self.warnings], "record": self.record}
        tmp = os.path.join(folder, "meta.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1, sort_keys=True)
        os.replace(tmp, os.path.join(folder, "meta.json"))         # last, so a folder with meta.json is a whole one

    @classmethod
    def load(cls, folder):
        with open(os.path.join(folder, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        with np.load(os.path.join(folder, "paths.npz")) as z:
            paths = Paths.from_arrays({k: z[k] for k in z.files})
        with np.load(os.path.join(folder, "moves.npz")) as z:
            moves = Moves.from_arrays({k: z[k] for k in z.files})
        gcode = os.path.join(folder, meta["gcode"]) if meta.get("gcode") else ""
        return cls(gcode, paths, moves, Estimate.from_dict(meta["estimate"]), [SliceWarning.from_dict(w) for w in meta["warnings"]], meta["record"])
