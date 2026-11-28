"""The Slicer add-on's engine finder: says in words when the engine is missing, finds it when it is there, never raises."""
import faulthandler; faulthandler.dump_traceback_later(60, exit=True)
import os, sys, tempfile, importlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "addons_src", "slicer"))
import slicer_engine as se

assert not any(n == se.MODULE for n in sys.modules), "the engine module is not loaded to begin with"

# 1. nothing downloaded: a clear sentence, not a traceback
st = se.status()
assert set(st) == {"available", "version", "reason"}
if st["available"]:
    print("note: a real orca_core is installed here; the 'missing' checks are skipped")
else:
    assert st["version"] == "" and "downloaded" in st["reason"] and "Traceback" not in st["reason"], st
    assert se.load() is None

# 2. a folder that does not exist leaves the path alone
tmp = tempfile.mkdtemp()
before = list(sys.path)
assert se.add_to_path(tmp) is False and sys.path == before
assert se.engine_folder(tmp) == os.path.join(tmp, "engine", "orca_core")

# 3. a fake engine in the right place is found and its version is reported (a stand-in: the real one is built by engines/orca_core)
if not st["available"]:
    f = se.engine_folder(tmp)
    os.makedirs(f)
    with open(os.path.join(f, "orca_core.py"), "w") as fh:
        fh.write('__version__ = "2.5.2-test"\n')
    st2 = se.status(tmp)
    assert st2 == {"available": True, "version": "2.5.2-test", "reason": ""}, st2
    assert se.load().__version__ == "2.5.2-test"
    sys.modules.pop(se.MODULE, None); sys.path.remove(f)
    importlib.invalidate_caches()

    # 4. an engine that is there but cannot load (a missing DLL looks like this): said in words, not raised
    f = se.engine_folder(tempfile.mkdtemp())
    os.makedirs(f)
    with open(os.path.join(f, "orca_core.py"), "w") as fh:
        fh.write('raise OSError("the DLL tbb12.dll was not found")\n')
    sys.path.insert(0, f); importlib.invalidate_caches()
    st3 = se.status()
    assert st3["available"] is False and "cannot be loaded" in st3["reason"] and "tbb12.dll" in st3["reason"], st3
    assert se.load() is None
    sys.path.remove(f); sys.modules.pop(se.MODULE, None)

print("slicer engine finder: ok")
