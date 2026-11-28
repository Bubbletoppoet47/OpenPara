"""Printers, processes and filaments: Orca's own vendor profiles, read and resolved here (plan chapter 9).

The profiles are Orca's files, unchanged: a folder of vendors (`Elegoo.json` is the index of a vendor, `Elegoo/machine`, `Elegoo/process` and
`Elegoo/filament` hold the presets), or the same thing in a zip file.  A preset names the one it inherits from and holds only what differs;
`resolve` follows the chain up to the root the way Orca's PresetBundle does, so the settings are the ones Orca's window would use (the
parity test, engines/orca_core/tests/parity.py, runs the engine on exactly such resolved files).

    p = Profiles.open()                                  # ORCA_CORE_PROFILES, or the `profiles` folder of this package
    p.vendors()                                          # ['Elegoo', 'Creality', ...]
    p.machines("Elegoo")                                 # the printers a person can pick (one per nozzle size)
    p.processes("Elegoo Centauri Carbon 0.4 nozzle")     # the print profiles that fit that printer
    p.filaments("Elegoo Centauri Carbon 0.4 nozzle")     # the filaments that fit
    settings = p.settings("Elegoo Centauri Carbon 0.4 nozzle", "0.20mm Standard @Elegoo CC 0.4 nozzle", "Elegoo PLA @ECC",
                          overrides={"sparse_infill_density": "30%"})
    job = Job(settings)

Nothing here needs the compiled engine.
"""
import json
import os
import re
import zipfile

from .errors import OrcaCoreError

KINDS = ("machine", "process", "filament")
_INDEX_LIST = {"machine": "machine_list", "process": "process_list", "filament": "filament_list", "machine_model": "machine_model_list"}
# keys of a preset file that describe the preset and are not settings
_META = {"name", "type", "from", "instantiation", "inherits", "setting_id", "version", "description", "model_id", "machine_tech", "family",
         "bed_model", "bed_texture", "hotend_model", "default_materials", "is_custom_defined"}
# the libraries a preset may inherit from when its own vendor does not have the parent (Orca keeps one namespace for all vendors)
_LIBRARIES = ("OrcaFilamentLibrary", "Custom")


class ProfileError(OrcaCoreError):
    """A printer, process or filament that is not in the profiles, a choice that does not fit together, or a profiles folder that is not there."""


class Preset:
    """What a list shows about a preset (the file is read when it is resolved, not before)."""
    def __init__(self, kind, vendor, name, sub_path, raw):
        self.kind, self.vendor, self.name, self.sub_path = kind, vendor, name, sub_path
        self.instantiation = str(raw.get("instantiation", "false")).lower() == "true"
        self.inherits = raw.get("inherits") or None
        cp = raw.get("compatible_printers") or []
        self.compatible_printers = list(cp) if isinstance(cp, list) else [cp]
        self.condition = raw.get("compatible_printers_condition") or ""
        self.raw = raw

    def __repr__(self):
        return "Preset(%s %r, %s)" % (self.kind, self.name, self.vendor)


# ---- where the files are: a folder or a zip with the same layout
class _Folder:
    def __init__(self, root):
        self.root = root

    def read(self, rel):
        with open(os.path.join(self.root, *rel.split("/")), "rb") as f:
            return f.read()

    def exists(self, rel):
        return os.path.isfile(os.path.join(self.root, *rel.split("/")))

    def vendors(self):
        return sorted(n[:-5] for n in os.listdir(self.root) if n.endswith(".json") and os.path.isdir(os.path.join(self.root, n[:-5])))


class _Zip:
    def __init__(self, path):
        self.z = zipfile.ZipFile(path)
        self.names = set(self.z.namelist())

    def read(self, rel):
        return self.z.read(rel)

    def exists(self, rel):
        return rel in self.names

    def vendors(self):
        return sorted(n[:-5] for n in self.names if n.endswith(".json") and "/" not in n and any(m.startswith(n[:-5] + "/") for m in self.names))


def default_location():
    """ORCA_CORE_PROFILES, else the `profiles` folder next to this package's resources; '' when there is none."""
    env = os.environ.get("ORCA_CORE_PROFILES")
    if env and (os.path.isdir(env) or os.path.isfile(env)):
        return env
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "profiles")
    for cand in (here, here + ".zip"):
        if os.path.exists(cand):
            return cand
    return ""


class Profiles:
    """Orca's vendor profiles from a folder (or zip), with the person's own presets from `user_dir` if given (same JSON, same folders:
    user_dir/<kind>/<name>.json; a user preset names the preset it was copied from in "inherits")."""

    def __init__(self, location, user_dir=None):
        if not location or not os.path.exists(location):
            raise ProfileError("The printer profiles are not there (looked in %r). Download them in the slicer add-on's settings." % (location,))
        self.location = location
        self.src = _Folder(location) if os.path.isdir(location) else _Zip(location)
        self.user_dir = user_dir
        self._vendor_index = {}          # vendor -> {"info": {...}, "kinds": {kind: {name: sub_path}}}
        self._presets = {}               # (vendor, kind, name) -> Preset
        self._resolved = {}

    @classmethod
    def open(cls, location=None, user_dir=None):
        return cls(location or default_location(), user_dir)

    # ---- the vendor indexes
    def vendors(self):
        return self.src.vendors()

    def vendor_info(self, vendor):
        """The vendor's own index (`name`, `version`, `description`, and the lists of what it has)."""
        return self._index(vendor)["info"]

    def _index(self, vendor):
        ix = self._vendor_index.get(vendor)
        if ix is None:
            rel = vendor + ".json"
            if not self.src.exists(rel):
                raise ProfileError("There is no vendor %r in the profiles." % vendor)
            info = json.loads(self.src.read(rel).decode("utf-8-sig"))
            kinds = {k: {e["name"]: e["sub_path"] for e in info.get(lst, [])} for k, lst in _INDEX_LIST.items()}
            ix = self._vendor_index[vendor] = {"info": info, "kinds": kinds}
        return ix

    def _preset(self, vendor, kind, name):
        key = (vendor, kind, name)
        p = self._presets.get(key)
        if p is None:
            sub = self._index(vendor)["kinds"][kind].get(name)
            if sub is None:
                return None
            raw = json.loads(self.src.read(vendor + "/" + sub).decode("utf-8-sig"))
            p = self._presets[key] = Preset(kind, vendor, name, sub, raw)
        return p

    def _user_preset(self, kind, name):
        if not self.user_dir:
            return None
        path = os.path.join(self.user_dir, kind, name + ".json")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8-sig") as f:
            raw = json.load(f)
        raw.setdefault("instantiation", "true")
        return Preset(kind, "User", name, path, raw)

    # ---- lists
    def models(self, vendor):
        """[{name, nozzle_diameter: [mm], default_materials: [names]}] of the printer models of a vendor, as its index lists them."""
        out = []
        for name, sub in self._index(vendor)["kinds"]["machine_model"].items():
            try:
                raw = json.loads(self.src.read(vendor + "/" + sub).decode("utf-8-sig"))
            except KeyError:
                continue
            out.append({"name": name, "vendor": vendor,
                        "nozzle_diameter": [float(x) for x in str(raw.get("nozzle_diameter", "")).split(";") if x.strip()],
                        "default_materials": [x for x in str(raw.get("default_materials", "")).split(";") if x]})
        return out

    def machines(self, vendor, model=None):
        """The printer presets a person can pick (one per model and nozzle size), as Presets.  model narrows to one printer model."""
        out = []
        for name in self._index(vendor)["kinds"]["machine"]:
            p = self._preset(vendor, "machine", name)
            if p and p.instantiation and (model is None or p.raw.get("printer_model") == model):
                out.append(p)
        return out

    def _find_machine(self, name, vendor=None):
        for v in ([vendor] if vendor else self.vendors()):
            p = self._preset(v, "machine", name) if name in self._index(v)["kinds"]["machine"] else None
            if p:
                return p
        u = self._user_preset("machine", name)
        if u:
            return u
        raise ProfileError("There is no printer profile named %r." % name)

    def _listed(self, kind, machine, vendor=None, include_libraries=True):
        m = self._find_machine(machine, vendor)
        mres = self.resolve("machine", machine, m.vendor if m.vendor != "User" else None)
        vendors = [m.vendor] if m.vendor != "User" else [vendor] if vendor else []
        if include_libraries:
            vendors += [v for v in _LIBRARIES if v not in vendors and v in self.vendors()]
        out = []
        for v in vendors:
            if v == "User":
                continue
            for name in self._index(v)["kinds"][kind]:
                p = self._preset(v, kind, name)
                if p and p.instantiation and self._fits(p, machine, mres):
                    out.append(p)
        if self.user_dir:
            d = os.path.join(self.user_dir, kind)
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if fn.endswith(".json"):
                        p = self._user_preset(kind, fn[:-5])
                        if p and (not p.compatible_printers or machine in p.compatible_printers):
                            out.append(p)
        return out

    def processes(self, machine, vendor=None):
        """The print profiles (layer height, walls, infill, speeds) that fit this printer preset."""
        return self._listed("process", machine, vendor, include_libraries=False)

    def filaments(self, machine, vendor=None):
        """The filaments that fit this printer preset: the vendor's own, and the generic ones of OrcaFilamentLibrary."""
        return self._listed("filament", machine, vendor)

    def _fits(self, p, machine, machine_resolved):
        """Orca's rule: a preset is offered for a printer when it names the printer, or names none and its condition holds for it.  Both are
        settings like any other, so they come from the resolved preset (a child that names none inherits its parent's)."""
        r = self.resolve(p.kind, p.name, p.vendor if p.vendor != "User" else None)
        names = r.get("compatible_printers") or []
        if names:
            return machine in (names if isinstance(names, list) else [names])
        cond = r.get("compatible_printers_condition") or ""
        if cond:
            ok = evaluate_condition(cond, machine_resolved)
            return True if ok is None else ok          # a condition this module cannot read does not hide the preset
        return True

    # ---- resolving
    def _lookup(self, kind, name, vendor=None):
        """The preset `name` of this kind: the user's, else the vendor's, else a library's, else any vendor's (Orca keeps one namespace)."""
        u = self._user_preset(kind, name)
        if u:
            return u
        order = ([vendor] if vendor else []) + [v for v in _LIBRARIES if v != vendor] + [v for v in self.vendors() if v != vendor and v not in _LIBRARIES]
        for v in order:
            if v in self.vendors() and name in self._index(v)["kinds"][kind]:
                return self._preset(v, kind, name)
        return None

    def resolve(self, kind, name, vendor=None, _chain=()):
        """The preset with the presets it inherits from merged in (the child's keys win), as {key: value}.  `inherits` and the keys that only
        describe the preset are left out."""
        if kind not in KINDS:
            raise ProfileError("A preset is a machine, a process or a filament, not %r." % kind)
        key = (kind, name, vendor)
        if not _chain and key in self._resolved:
            return dict(self._resolved[key])
        if (kind, name) in _chain:
            raise ProfileError("The profile %r inherits from itself (%s)." % (name, " -> ".join(n for _k, n in _chain)))
        p = self._lookup(kind, name, vendor)
        if p is None:
            raise ProfileError("There is no %s profile named %r." % (kind, name))
        merged = {}
        if p.inherits:
            try:
                merged = self.resolve(kind, p.inherits, p.vendor if p.vendor != "User" else vendor, _chain + ((kind, name),))
            except ProfileError as e:
                raise ProfileError("The profile %r inherits from %r: %s" % (name, p.inherits, e)) from None
        merged.update({k: v for k, v in p.raw.items() if k not in ("inherits",)})
        if not _chain:
            out = {k: v for k, v in merged.items() if k not in _META}
            self._resolved[key] = out
            return dict(out)
        return merged

    # ---- the settings of a job
    def settings(self, machine, process, filament, overrides=None, vendor=None):
        """The settings for a Job from a printer, a print profile and a filament (names of presets), with `overrides` on top: {key: value}.

        Raises ProfileError, in words, if a name is not in the profiles or the process or filament is not made for the printer.  The names of
        the three presets go into `printer_settings_id`, `print_settings_id` and `filament_settings_id`, as Orca's window writes them."""
        m = self._find_machine(machine, vendor)
        mres = self.resolve("machine", machine, m.vendor if m.vendor != "User" else vendor)
        for kind, name in (("process", process), ("filament", filament)):
            p = self._lookup(kind, name, m.vendor if m.vendor != "User" else vendor)
            if p is None:
                raise ProfileError("There is no %s profile named %r." % (kind, name))
            if p.vendor != "User" and not self._fits(p, machine, mres):
                raise ProfileError("The %s profile %r is not made for the printer %r." % (kind, name, machine))
        out = dict(mres)
        out.update(self.resolve("process", process, m.vendor if m.vendor != "User" else vendor))
        out.update(self.resolve("filament", filament, m.vendor if m.vendor != "User" else vendor))
        out["printer_settings_id"] = machine
        out["print_settings_id"] = process
        out["filament_settings_id"] = [filament]
        for k, v in (overrides or {}).items():
            out[str(k)] = v
        return out


# ---- the conditions of `compatible_printers_condition`
class _Unreadable(Exception):
    pass


_TOKEN = re.compile(r"\s*(?:(?P<re>=~|!~)|(?P<op>==|!=|<=|>=|<|>|\(|\)|!)|(?P<rx>/(?:\\.|[^/\\])*/)|(?P<str>\"[^\"]*\"|'[^']*')|(?P<num>-?[0-9]+(?:\.[0-9]+)?)|(?P<id>[A-Za-z_][A-Za-z_0-9]*(?:\[[0-9]+\])?))")


def _tokens(text):
    pos, out = 0, []
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise _Unreadable(text[pos:pos + 20])
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


def evaluate_condition(text, preset, config_keys=None):
    """Orca's `compatible_printers_condition` for a (resolved) printer preset: True, False, or None when the expression uses something this
    reader does not know (the caller then does not hide the preset).  Covers what the shipped profiles use: `printer_notes=~/.*ECC.*/`,
    `nozzle_diameter[0]==0.4`, `!~`, `and`, `or`, `not`, parentheses and plain flags such as `single_extruder_multi_material`."""
    try:
        toks = _tokens(text)
        pos = [0]

        def peek():
            return toks[pos[0]] if pos[0] < len(toks) else (None, None)

        def take():
            t = peek()
            pos[0] += 1
            return t

        def value(tok):
            kind, v = tok
            if kind == "num":
                return float(v)
            if kind == "str":
                return v[1:-1]
            if kind == "id":
                m = re.match(r"([A-Za-z_0-9]+)(?:\[([0-9]+)\])?$", v)
                key, idx = m.group(1), m.group(2)
                if key not in preset:
                    if key in ("single_extruder_multi_material",):
                        return 0.0
                    raise _Unreadable(key)
                raw = preset[key]
                if idx is not None:
                    raw = raw[int(idx)] if isinstance(raw, list) else raw
                elif isinstance(raw, list):
                    raw = raw[0] if raw else ""
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    return str(raw)
            raise _Unreadable(str(v))

        def primary():
            kind, v = peek()
            if kind == "op" and v == "(":
                take()
                r = expr_or()
                if take() != ("op", ")"):
                    raise _Unreadable(")")
                return r
            if kind == "op" and v == "!":
                take()
                return not primary()
            if kind == "id" and v == "not":
                take()
                return not primary()
            left = value(take())
            k2, v2 = peek()
            if k2 == "re":
                take()
                rk, rv = take()
                if rk != "rx":
                    raise _Unreadable(rv)
                hit = re.search(rv[1:-1], str(left if not isinstance(left, float) else repr(left)), re.S) is not None
                return hit if v2 == "=~" else not hit
            if k2 == "op" and v2 in ("==", "!=", "<=", ">=", "<", ">"):
                take()
                right = value(take())
                if isinstance(left, float) != isinstance(right, float):
                    left, right = str(left), str(right)
                return {"==": left == right, "!=": left != right, "<=": left <= right, ">=": left >= right, "<": left < right, ">": left > right}[v2]
            return bool(left)

        def expr_and():
            r = primary()
            while peek() == ("id", "and"):
                take()
                r = primary() and r
            return r

        def expr_or():
            r = expr_and()
            while peek() == ("id", "or"):
                take()
                r = expr_and() or r
            return r

        result = expr_or()
        if pos[0] != len(toks):
            raise _Unreadable("end")
        return bool(result)
    except (_Unreadable, IndexError, KeyError, TypeError):
        return None
