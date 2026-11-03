"""legacy.py - old files made with the assembly sketch link (AS_ variables, nested configurations) open as plain files.

The linked variables and the nested configuration tree no longer exist.  When a file that has them is read, every {AS_<config>_<name>}
(and {AS_@_<name>}, the cell's own configuration) is replaced by the number it last had, the link and the tree are dropped, and the children
stay as ordinary configurations.  Nothing is lost but the link.  No Qt in here."""
import re

_TOKEN = re.compile(r"\{\s*AS_([^{}]*?)\s*\}")


def _value(vals, config, var):
    row = (vals or {}).get(config) or {}
    return row.get(var)


def _number(x):
    return repr(round(float(x), 10)).rstrip("0").rstrip(".") if float(x) != int(float(x)) else str(int(float(x)))


def _replace(text, vals, own):
    def one(m):
        body = m.group(1)
        if body.startswith("@_") and own is not None:
            cfg, var = own, body[2:]
            v = _value(vals, cfg, var)
        else:
            v = None
            for cfg in sorted(vals or {}, key=len, reverse=True):          # the configuration name may contain underscores and spaces
                if body.startswith(cfg + "_"):
                    v = _value(vals, cfg, body[len(cfg) + 1:])
                    if v is not None:
                        break
        return _number(v) if v is not None else "0"
    return _TOKEN.sub(one, text)


def _walk(x, vals, own):
    if isinstance(x, str):
        return _replace(x, vals, own) if "{AS_" in x.replace("{ AS_", "{AS_") else x
    if isinstance(x, list):
        return [_walk(i, vals, own) for i in x]
    if isinstance(x, dict):
        return {k: _walk(v, vals, own) for k, v in x.items()}
    return x


def flatten(d):
    """The dict of a file with the link taken out (the same dict is returned, changed in place)."""
    g = d.get("gsv")
    cfg = d.get("cfg") or {}
    if not g and "tree" not in cfg and "cids" not in cfg:
        return d
    vals = (g or {}).get("vals") or {}
    leaf = (cfg.get("tree") or {}).get("leaf") or {}
    for key in ("params", "exprs", "features", "kinds"):
        if key in d:
            d[key] = _walk(d[key], vals, None)
    cells = cfg.get("cells") or {}
    for name in list(cells):
        suffix = (leaf.get(name) or {}).get("suffix") or name.split(" · ")[-1]
        own = suffix if suffix in vals else name
        cells[name] = _walk(cells[name], vals, own)
    for k in ("tree", "cids"):
        cfg.pop(k, None)
    d.pop("gsv", None)
    return d
