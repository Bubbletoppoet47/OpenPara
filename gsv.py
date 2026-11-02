"""gsv.py - Global Sketch Variables: the numbers an assembly sketch (.gpk) hands to the parts and assemblies linked to it.

A sketch variable `W` exported by the sketch configuration `Large` arrives in a part / assembly as the read-only global **AS-Large-W**
(one per exported variable per sketch configuration).  The hyphens make it unusable as a plain name in a formula, so a formula writes it in
braces:   {AS-Large-W} * 2 + 3.   Inside a configuration cell the configuration part can be the word @, which stands for the configuration
that owns the cell:   {AS-@-W}   - it is AS-Small-W in the configuration Small, AS-Large-W in Large, and a configuration that the sketch
adds later follows the sketch without anybody editing the cell.

What a file keeps (Document.gsv / Assembly.gsv):
    {"src": path of the .gpk (relative to the file), "configs": [sketch configuration names], "vars": [{"name", "kind", "role"}],
     "vals": {configuration: {variable: number}}, "mirrored": [configurations this file made / follows]}
kind: length (mm) | angle (degrees) | number;  role: driving (a dimension / symbol you set) | driven (measured from the geometry).
No Qt in here.
"""
import re

PREFIX = "AS-"
KINDS = ("length", "angle", "number")
ROLES = ("driving", "driven")

_TOKEN = re.compile(r"\{([^{}]*)\}")


def full_name(config, var):
    return f"{PREFIX}{config}-{var}"


def mangle_name(name):
    """The identifier that stands for the global `name` inside an evaluated formula."""
    return "_gsv_" + name.encode("utf-8").hex()


def mangle(text):
    """Formula text -> text a plain evaluator can read: every {AS-...} becomes an identifier.  Other text is untouched."""
    text = str(text)
    if "{" not in text:
        return text
    return _TOKEN.sub(lambda m: mangle_name(m.group(1).strip()) if m.group(1).strip().startswith(PREFIX) else m.group(0), text)


def mask(text):
    """Same text with each {AS-...} replaced by underscores of the same length (a name for the parser, same column offsets)."""
    return _TOKEN.sub(lambda m: "_" * len(m.group(0)) if m.group(1).strip().startswith(PREFIX) else m.group(0), str(text))


def has_token(text):
    return isinstance(text, str) and "{" + PREFIX in text.replace("{ ", "{")


def has_binding(text):
    """Does the cell follow the configuration it sits in ({AS-@-W})?"""
    return isinstance(text, str) and ("{" + PREFIX + "@-") in text


def resolve_at(text, config):
    """{AS-@-W} -> {AS-<config>-W}."""
    if not has_binding(text):
        return text
    return str(text).replace("{" + PREFIX + "@-", "{" + PREFIX + config + "-")


def keep_binding(cell, value, config):
    """A cell that is bound and whose resolved text is `value` keeps its binding when the table is read back from the document."""
    return has_binding(cell) and resolve_at(cell, config) == value


def flat(g):
    """{full name: number} of a gsv record (or {})."""
    if not g:
        return {}
    out = {}
    for cfg, row in (g.get("vals") or {}).items():
        for var, v in row.items():
            out[full_name(cfg, var)] = float(v)
    return out


def namespace(g):
    """{identifier: number} to add to the names a formula can use."""
    return {mangle_name(k): v for k, v in flat(g).items()}


def kinds_of(g):
    """{full name: (kind, role)}"""
    out = {}
    if not g:
        return out
    info = {v["name"]: v for v in g.get("vars") or []}
    for cfg in g.get("configs") or []:
        for var, v in info.items():
            out[full_name(cfg, var)] = (v.get("kind", "number"), v.get("role", "driving"))
    return out


def rows(g):
    """[(full name, number, kind, role)] in table order: by variable, then configuration."""
    out = []
    if not g:
        return out
    vals = g.get("vals") or {}
    for v in g.get("vars") or []:
        for cfg in g.get("configs") or []:
            x = vals.get(cfg, {}).get(v["name"])
            if x is not None:
                out.append((full_name(cfg, v["name"]), float(x), v.get("kind", "number"), v.get("role", "driving")))
    return out


def reserved(name):
    """A global / dimension / configuration-column name may not start with the sketch prefix."""
    return str(name).startswith(PREFIX)
