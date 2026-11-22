"""pe_store.py - what the PDF editor remembers between runs, in <user folder>/pdf_editor.json (no window, so it is tested without one).

    positions   {pdf path: {"sent": sentence marker, "zoom": zoom, "page": page}}  the last 60 PDFs (where you stopped reading)
    open        the PDFs and page projects that were open in the editor tab, in tab order
    voice, rate the Windows voice and the speed
    auto        {pdf path: True}  the PDFs that save their highlights by themselves
    last_dir    the folder of the last PDF that was opened

A read that fails (no file, a damaged file) gives the defaults; a write that fails is ignored: this file is a convenience, never a reason for an error.
"""
import json
import os

FILE = "pdf_editor.json"
MAX_POSITIONS = 60
DEFAULTS = {"positions": {}, "open": [], "voice": None, "rate": 1, "auto": {}, "last_dir": ""}


def _file():
    import paths
    return os.path.join(paths.user_dir(), FILE)


def key(path):
    """The same file always has the same key (case and slashes do not matter on Windows)."""
    return os.path.normcase(os.path.abspath(path)) if path else ""


class Store:
    def __init__(self, path=None):
        self.file = path or _file()
        self.data = json.loads(json.dumps(DEFAULTS))
        self.read()

    def read(self):
        try:
            with open(self.file, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(d, dict):
            return
        for k, default in DEFAULTS.items():
            v = d.get(k, default)
            if isinstance(default, dict) and not isinstance(v, dict):
                v = {}
            elif isinstance(default, list) and not isinstance(v, list):
                v = []
            self.data[k] = v

    def flush(self):
        """Writes the file (all at once: a crash in the middle cannot leave half of it)."""
        pos = self.data["positions"]
        for k in list(pos)[:-MAX_POSITIONS]:
            pos.pop(k, None)
        try:
            tmp = f"{self.file}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.file)
        except OSError:
            pass

    # -- reading positions
    def position(self, path):
        p = self.data["positions"].get(key(path))
        return dict(p) if isinstance(p, dict) else None

    def set_position(self, path, sent, zoom, page):
        k = key(path)
        pos = self.data["positions"]
        pos.pop(k, None)                          # the newest goes last, so that the oldest ones are the ones dropped
        pos[k] = {"sent": sent, "zoom": float(zoom), "page": int(page)}

    # -- auto-save of highlights, per PDF
    def auto(self, path):
        return bool(self.data["auto"].get(key(path)))

    def set_auto(self, path, on):
        if on:
            self.data["auto"][key(path)] = True
        else:
            self.data["auto"].pop(key(path), None)

    # -- the rest
    def get(self, name, default=None):
        v = self.data.get(name)
        return default if v is None else v

    def set(self, name, value):
        self.data[name] = value
