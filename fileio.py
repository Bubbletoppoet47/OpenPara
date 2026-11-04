"""fileio.py - writing a file so that a crash (or a power cut) in the middle can never leave half of it: the text goes to a temporary file in the
same folder first and is renamed over the old one in one step."""
import os


def write_text(path, text, encoding="utf-8"):
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
