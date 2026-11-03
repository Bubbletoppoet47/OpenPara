"""cfg_tree.py - nested configurations: general configurations ("groups") whose children follow the assembly sketch.

A configuration that uses a variable of the assembly sketch is not a part of its own: it becomes a GROUP with one child (a "leaf", the thing that can be
activated) per assembly sketch configuration, named  <group> · <suffix>  - or  <group> · <variant> · <suffix>  when the group has feature variants.  The suffix
is the sketch configuration the child's linked variables follow ({AS_@_W} in a child's cell is the variable of the suffix).  Only the sketch adds, renames
and deletes children.  Every other configuration stays a regular one.

What is stored (cfg["tree"], next to the flat cfg["names"] / cfg["cells"] that the rest of the program keeps using):
    {"nid": n, "groups": [{"id", "name", "variants": [{"id", "name" or None, "aids": [sketch configuration ids that have a child here]}]}],
     "leaf": {child name: {"g": group id, "v": variant id, "aid": sketch configuration id, "suffix": sketch configuration name}}}
`o` is a part Document or an Assembly (anything with cfg, cfg_add / cfg_rename / cfg_delete and gsv).  No Qt in here."""
import re

import gsv

SEP = " · "
_TOKEN = re.compile(r"\{([^{}]*)\}")


def tree(o):
    return o.cfg.setdefault("tree", {"nid": 1, "groups": [], "leaf": {}})


def has_tree(o):
    t = o.cfg.get("tree")
    return bool(t and t.get("groups"))


def leaf(o, name):
    return (o.cfg.get("tree") or {}).get("leaf", {}).get(name)


def link_name(o, name):
    """The assembly sketch configuration a configuration follows: its suffix when it is a child, else its own name."""
    r = leaf(o, name)
    return r["suffix"] if r else name


def _nid(o, p):
    t = tree(o)
    t["nid"] += 1
    return f"{p}{t['nid']}"


def find_group(o, gid):
    return next((g for g in tree(o)["groups"] if g["id"] == gid), None)


def find_variant(g, vid):
    return next((v for v in g["variants"] if v["id"] == vid), None)


def leaf_name(g, v, suffix):
    return SEP.join([g["name"]] + ([v["name"]] if v.get("name") else []) + [suffix])


def children(o, g, v):
    """[child name] of one variant, in the order of the assembly sketch."""
    t = tree(o)
    order = {a: i for i, a in enumerate((o.gsv or {}).get("cids") or [])}
    mine = [(n, r) for n, r in t["leaf"].items() if r["g"] == g["id"] and r["v"] == v["id"]]
    return [n for n, r in sorted(mine, key=lambda x: order.get(x[1]["aid"], 1e9))]


def listing(o):
    """What the Configurations panel shows: ([(group, [(variant, [child names])])], [regular configuration names]).  Groups first, in the order they
    were made; the regular configurations below them in the order they were made."""
    t = tree(o)
    groups = [(g, [(v, children(o, g, v)) for v in g["variants"]]) for g in t["groups"]]
    regular = [n for n in o.cfg["names"] if n not in t["leaf"]]
    return groups, regular


def uses_link(o, name):
    row = o.cfg["cells"].get(name, {})
    return any(isinstance(c, str) and (gsv.has_token(c) or gsv.has_binding(c)) for c in row.values())


def bind_tokens(text, configs):
    """{AS_Long_W} -> {AS_@_W} for every sketch configuration name (the child's own suffix will pick the right one)."""
    if not isinstance(text, str) or "{" + gsv.PREFIX not in text:
        return text

    def one(m):
        inner = m.group(1).strip()
        if not inner.startswith(gsv.PREFIX) or inner.startswith(gsv.BIND):
            return m.group(0)
        for c in sorted(configs, key=len, reverse=True):
            if inner.startswith(gsv.PREFIX + c + "_"):
                return "{" + gsv.BIND + inner[len(gsv.PREFIX) + len(c) + 1:] + "}"
        return m.group(0)
    return _TOKEN.sub(one, text)


def _sketch(o):
    g = o.gsv or {}
    configs, cids = list(g.get("configs") or []), list(g.get("cids") or [])
    if len(cids) != len(configs):
        cids = ["n:" + c for c in configs]
    return configs, cids


def _add_leaf(o, g, v, aid, suffix, copy_of=None):
    name = leaf_name(g, v, suffix)
    if name not in o.cfg["names"]:
        o.cfg_add(name, copy_of=copy_of)
    tree(o)["leaf"][name] = {"g": g["id"], "v": v["id"], "aid": aid, "suffix": suffix}
    return name


def _bind_row(o, name, configs):
    row = o.cfg["cells"].get(name, {})
    for k, c in list(row.items()):
        row[k] = bind_tokens(c, configs)


def regroup(o):
    """Every regular configuration that uses a sketch variable becomes a group with one child per sketch configuration.  -> [messages]"""
    configs, cids = _sketch(o)
    msgs = []
    if not configs:
        return msgs
    t = tree(o)
    for name in [n for n in o.cfg["names"] if n not in t["leaf"]]:
        if not uses_link(o, name):
            continue
        g = {"id": _nid(o, "G"), "name": name, "variants": []}
        v = {"id": _nid(o, "V"), "name": None}
        g["variants"].append(v)
        t["groups"].append(g)
        first = leaf_name(g, v, configs[0])
        o.cfg_rename(name, first)
        t["leaf"][first] = {"g": g["id"], "v": v["id"], "aid": cids[0], "suffix": configs[0]}
        _bind_row(o, first, configs)
        act = o.cfg["active"]
        if act == first:                                                     # the live document takes the numbers of the child that is active, before any capture
            for k, c in o.cfg["cells"].get(first, {}).items():
                if gsv.has_binding(c):
                    o.cfg_write(k, gsv.resolve_at(c, configs[0]))
        for aid, suf in list(zip(cids, configs))[1:]:
            _add_leaf(o, g, v, aid, suf, copy_of=first)
        for n in children(o, g, v):
            _bind_row(o, n, configs)
        msgs.append(f"'{name}' now follows the assembly sketch: {len(configs)} nested configuration(s)")
    return msgs


def sync(o):
    """The sketch is the master: add the children a new sketch configuration needs, rename suffixes, delete children whose sketch configuration is gone.
    -> [messages]"""
    configs, cids = _sketch(o)
    t = tree(o)
    msgs = []
    if not t["groups"]:
        return msgs
    byaid = dict(zip(cids, configs))
    for g in t["groups"]:
        for v in g["variants"]:
            mine = {r["aid"]: n for n, r in t["leaf"].items() if r["g"] == g["id"] and r["v"] == v["id"]}
            base = next(iter(mine.values()), None)
            for aid in list(mine):
                n = mine[aid]
                if aid not in byaid:
                    try:
                        o.cfg_delete(n)
                        t["leaf"].pop(n, None)
                        msgs.append(f"configuration '{n}' removed because the sketch no longer has it")
                    except Exception:                                       # noqa: BLE001
                        msgs.append(f"'{n}' is no longer in the sketch but is the only configuration: kept")
                    continue
                if t["leaf"][n]["suffix"] != byaid[aid]:
                    old_suf = t["leaf"][n]["suffix"]
                    new = leaf_name(g, v, byaid[aid])
                    try:
                        o.cfg_rename(n, new)
                        r = t["leaf"].pop(n)
                        r["suffix"] = byaid[aid]
                        t["leaf"][new] = r
                        o.gsv_retarget(old_suf, byaid[aid])
                        msgs.append(f"configuration '{n}' renamed to '{new}'")
                    except Exception as ex:                                 # noqa: BLE001
                        msgs.append(f"could not rename '{n}': {ex}")
            for aid, suf in zip(cids, configs):
                if aid not in mine and base is not None:
                    _add_leaf(o, g, v, aid, suf, copy_of=base)
    return msgs


def migrate(o, mirrored, idmap):
    """A file from before nesting: its flat mirrored configurations become the children of one group called General."""
    configs, cids = _sketch(o)
    if not mirrored or has_tree(o):
        return []
    renames, adds, deletes, newmap = gsv.plan(mirrored, idmap, configs, cids)
    t = tree(o)
    g = {"id": _nid(o, "G"), "name": "General", "variants": []}
    v = {"id": _nid(o, "V"), "name": None}
    g["variants"].append(v)
    t["groups"].append(g)
    ren = dict(renames)
    byname = {}
    for n in mirrored:
        suf_name = ren.get(n, n)
        aid = newmap.get(suf_name)
        if aid is None or suf_name not in configs or n not in o.cfg["names"]:
            continue
        new = leaf_name(g, v, suf_name)
        if suf_name != n:
            o.gsv_retarget(n, suf_name)                                     # formulas that wrote {AS_<old name>_x}
        if _try_rename(o, n, new):
            t["leaf"][new] = {"g": g["id"], "v": v["id"], "aid": aid, "suffix": suf_name}
            byname[suf_name] = new
    for n in list(t["leaf"]):
        _bind_row(o, n, configs)
    return [f"{len(byname)} existing mirrored configuration(s) are now nested under 'General'"]


def _try_rename(o, a, b):
    try:
        o.cfg_rename(a, b)
        return True
    except Exception:                                                       # noqa: BLE001
        return False


def after_cell(o, name, key, val):
    """A cell was edited.  A sketch variable typed into a regular configuration makes it a group; typed into a child it is applied to every child of
    its variant (written as {AS_@_x}, each child follows its own suffix).  -> [messages]"""
    configs, _cids = _sketch(o)
    if not configs or not (isinstance(val, str) and gsv.has_token(val)):
        return []
    r = leaf(o, name)
    if r is None:
        return regroup(o)
    g = find_group(o, r["g"])
    v = find_variant(g, r["v"]) if g else None
    if v is None:
        return []
    bound = bind_tokens(val, configs)
    for n in children(o, g, v):
        o.cfg["cells"].setdefault(n, {})[key] = bound
    return []


def bind_column(o, key, var):
    """Make column `key` follow sketch variable `var` in the active configuration (and all children of its variant).  A regular configuration becomes a group."""
    name = o.cfg["active"]
    cell = "{" + gsv.BIND + var + "}"
    r = leaf(o, name)
    if r is None:
        o.cfg["cells"].setdefault(name, {})[key] = cell
        return regroup(o)
    g = find_group(o, r["g"])
    v = find_variant(g, r["v"])
    for n in children(o, g, v):
        o.cfg["cells"].setdefault(n, {})[key] = cell
    return []


def sever(o, name):
    """A child's link is cut: a new regular configuration with the child's other values; the linked cells become plain numbers (the child's current
    ones, as a starting value).  The child stays.  -> new name"""
    r = leaf(o, name)
    if r is None:
        raise ValueError("that configuration is not a nested one")
    g = find_group(o, r["g"])
    v = find_variant(g, r["v"])
    base = SEP.join([g["name"]] + ([v["name"]] if v.get("name") else []) + [r["suffix"]]) + " (unlinked)"
    new, i = base, 2
    while new in o.cfg["names"]:
        new, i = f"{base} {i}", i + 1
    o.cfg_capture()
    o.cfg_add(new, copy_of=name)
    row = o.cfg["cells"][new]
    vals = (o.gsv or {}).get("vals", {}).get(r["suffix"], {})
    for k, c in list(row.items()):
        if isinstance(c, str) and (gsv.has_binding(c) or gsv.has_token(c)):
            txt = gsv.resolve_at(c, r["suffix"])
            try:
                row[k] = _number_of(o, txt, vals)
            except Exception:                                               # noqa: BLE001
                row[k] = txt
    return new


def _number_of(o, text, vals):
    ns = {gsv.mangle_name(gsv.full_name(c, v)): float(x) for c, row in (o.gsv or {}).get("vals", {}).items() for v, x in row.items()}
    return float(eval(gsv.mangle(text), {"__builtins__": {}}, ns))


def rename_group(o, gid, new):
    new = new.strip()
    g = find_group(o, gid)
    if g is None or not new:
        raise ValueError("empty name")
    if any(x["name"] == new for x in tree(o)["groups"] if x is not g) or (new in o.cfg["names"] and new not in {n for n in tree(o)["leaf"]}):
        raise ValueError("that name is already used")
    old = g["name"]
    g["name"] = new
    _rename_all(o, g)
    return old


def rename_variant(o, gid, vid, new):
    new = new.strip() or None
    g = find_group(o, gid)
    v = find_variant(g, vid) if g else None
    if v is None:
        raise ValueError("no such variant")
    v["name"] = new
    _rename_all(o, g)


def _rename_all(o, g):
    t = tree(o)
    for v in g["variants"]:
        for n in list(children(o, g, v)):
            r = t["leaf"][n]
            new = leaf_name(g, v, r["suffix"])
            if new != n:
                o.cfg_rename(n, new)
                t["leaf"][new] = t["leaf"].pop(n)


def delete_group(o, gid):
    """Delete a group with its children (the last configuration of a file is never deleted)."""
    g = find_group(o, gid)
    t = tree(o)
    if g is None:
        return
    for n in [n for n, r in t["leaf"].items() if r["g"] == gid]:
        o.cfg_delete(n)
        t["leaf"].pop(n, None)
    t["groups"].remove(g)


def suppress_state(o, name):
    row = o.cfg["cells"].get(name, {})
    return {k: bool(x) for k, x in row.items() if k.startswith("s:") and x}


def feature_change(o, name, key, value):
    """The active child's feature `key` ("s:<id>") is about to become `value`.  -> ("same", None) nothing changes, ("switch", child) an existing variant
    already has that feature state (activate it), ("new", None) a new variant is needed."""
    r = leaf(o, name)
    if r is None:
        return "same", None
    want = suppress_state(o, name)
    if value:
        want[key] = True
    else:
        want.pop(key, None)
    if want == suppress_state(o, name):
        return "same", None
    g = find_group(o, r["g"])
    for v in g["variants"]:
        if v["id"] == r["v"]:
            continue
        for n in children(o, g, v):
            if tree(o)["leaf"][n]["aid"] == r["aid"] and suppress_state(o, n) == want:
                return "switch", n
    return "new", None


def make_variant(o, name, key, value, variant_name):
    """New variant of the group of child `name` with feature `key` set to `value` in every child; the original variant is unchanged.  -> the new child
    that matches `name`'s suffix."""
    r = leaf(o, name)
    g = find_group(o, r["g"])
    v0 = find_variant(g, r["v"])
    v = {"id": _nid(o, "V"), "name": variant_name.strip()}
    g["variants"].append(v)
    o.cfg_capture()
    mine = None
    for n in children(o, g, v0):
        rr = tree(o)["leaf"][n]
        new = _add_leaf(o, g, v, rr["aid"], rr["suffix"], copy_of=n)
        o.cfg["cells"].setdefault(new, {})[key] = bool(value)
        if rr["aid"] == r["aid"]:
            mine = new
    return mine
