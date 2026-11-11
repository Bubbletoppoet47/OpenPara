"""The Remote helper and OpenPara's side of it, on this machine: the access code handshake (right, wrong, locked out, none set), the encrypted
messages, the screen (whole picture, only what changed, JPEG), keyboard and mouse events, files (both ways, folders, stop, check), commands,
the switches that turn a part off, asking on the screen, searching the network - and the real X11 screen / keyboard / mouse back ends."""
import os, sys, tempfile, time, threading, json, socket, struct, hashlib, zlib, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "addons_src", "remote"))
CFG = os.environ["OPRH_CONFIG_DIR"] = tempfile.mkdtemp(prefix="opara_rh_")
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import openpara_remote_helper as H, remote_link as RL

# ---- the helper is one file that needs nothing but Python
src = open(H.__file__, encoding="utf-8").read()
import ast
mods = {n.names[0].name.split(".")[0] for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import)} | \
       {n.module.split(".")[0] for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
allowed = set(sys.stdlib_module_names) | {"cv2", "numpy", "PIL"}                  # the last three only when they happen to be installed
assert mods <= allowed, mods - allowed

# ---- the numbers of the handshake: a safe prime, 2 in its prime-order subgroup, M and N in it too
def probably_prime(n, bases=(2, 3, 5, 7, 11, 13)):
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2; s += 1
    for a in bases:
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True
Q = (H.P - 1) // 2
assert H.P.bit_length() == 2048 and probably_prime(H.P) and probably_prime(Q)
assert pow(H.G, Q, H.P) == 1 and pow(H.M_EL, Q, H.P) == 1 and pow(H.N_EL, Q, H.P) == 1 and H.M_EL != H.N_EL and H.M_EL not in (0, 1)

# ---- access codes
c = H.new_code(); assert len(c) == 14 and len(H.normalize_code(c)) == 12 and set(H.normalize_code(c)) <= set(H.CODE_ALPHABET)
assert H.normalize_code(" abcd-efgh jkmn ") == "ABCDEFGHJKMN"
try:
    H.set_code({}, "short"); raise SystemExit("a short code was accepted")
except H.RemoteError:
    pass
cfg = H.set_code({"name": "Test Pi"}, "ABCD-EFGH-JKMN")
assert "ABCD" not in json.dumps(cfg), "the code itself is not stored"
cfg_p = H.set_code({}, "ABCD-EFGH-JKMN", {"name": "pbkdf2", "iter": 100000})
for bad in ({"name": "scrypt", "n": 1 << 30, "r": 8, "p": 1}, {"name": "pbkdf2", "iter": 10 ** 9}, {"name": "x"}):
    try:
        H.derive_w("x" * 8, b"s" * 16, bad); raise SystemExit("a made-up setting was accepted")
    except H.RemoteError:
        pass
H.save_config(cfg); assert H.load_config()["w"] == cfg["w"]


class FakeScreen:
    name = "fake"
    def __init__(self, w=320, h=200):
        self.w, self.h = w, h
        self.buf = bytearray(os.urandom(64) * (w * h * 4 // 64))
    def grab(self):
        return self.w, self.h, 4, "bgrx", bytes(self.buf)
    def paint(self, x, y, w, h, bgrx):
        for r in range(y, y + h):
            self.buf[(r * self.w + x) * 4:(r * self.w + x + w) * 4] = bytes(bgrx) * w


class FakeInput(H._Keys):
    name = "fake"
    shift_code = "SHIFT"
    def __init__(self):
        super().__init__(); self.log = []
    def move(self, x, y, w, h): self.log.append(("move", x, y, w, h))
    def button(self, b, down): self.log.append(("btn", b, down))
    def wheel(self, dy, dx=0): self.log.append(("wheel", dy, dx))
    def lookup(self, key):
        if key in H.KEYSYMS: return key, None
        return (key.lower(), key.isupper()) if len(key) == 1 else None
    def raw_key(self, code, down): self.log.append(("key", code, down))
    def flush(self): self.log.append(("flush",))


def helper(cfg, **kw):
    hp = H.Helper(cfg, port=0, bind="127.0.0.1", discovery=False, **kw)
    hp.screen, hp.inp = FakeScreen(), FakeInput()
    return hp.start()

hp = helper(cfg)
t0 = time.time()
link = RL.Link("127.0.0.1", hp.port, "abcd efgh jkmn", name="Tester").connect()
assert time.time() - t0 < 5
i = link.info
assert i["name"] == "Test Pi" and i["screen"] == {"ok": True, "w": 320, "h": 200, "backend": "fake"} and i["input"]["ok"] and i["files"] and i["commands"]
assert link.label() == "Test Pi" and not link.closed
log = open(os.path.join(CFG, "connections.log")).read()
assert "connected: Tester (127.0.0.1)" in log

# ---- what goes over the wire is not readable: the same request twice gives different bytes, and a changed byte is refused
a, b = socket.socketpair()
m = hashlib.sha256(b"k").digest()
ca, cb = H.Channel(a, m, True), H.Channel(b, m, False)
ca.send({"op": "x", "secret": "hello world"}, b"payload-payload")
raw = b.recv(4096, socket.MSG_PEEK)
assert b"hello" not in raw and b"payload" not in raw
assert cb.recv() == ({"op": "x", "secret": "hello world"}, b"payload-payload")
ca.send({"op": "x", "secret": "hello world"}, b"payload-payload")
raw2 = b.recv(4096, socket.MSG_PEEK); assert raw2 != raw
cb.recv()
ca.send({"op": "y"}, b"1234")
blob = bytearray(b.recv(4096)); blob[6] ^= 1
c2, d2 = socket.socketpair(); d2.sendall(bytes(blob))
cb.sock = c2
try:
    cb.recv(); raise SystemExit("a changed message was accepted")
except ConnectionError as e:
    assert "damaged or changed" in str(e)
for s in (a, b, c2, d2): s.close()

# ---- wrong code: said in words, written to the log; five in a row lock that address out; the right code then waits too
for n in range(H.FAIL_LIMIT):
    try:
        RL.Link("127.0.0.1", hp.port, "ABCD-EFGH-JKMX").connect(); raise SystemExit("a wrong code got in")
    except RL.RemoteError as e:
        assert str(e) == "Wrong access code.", str(e)
assert "WRONG access code from 127.0.0.1" in open(os.path.join(CFG, "connections.log")).read()
try:
    RL.Link("127.0.0.1", hp.port, "ABCD-EFGH-JKMN").connect(); raise SystemExit("locked out, but got in")
except RL.RemoteError as e:
    assert "Too many wrong access codes" in str(e) and "minute" in str(e), str(e)
hp.guard.fails.clear()
assert not link.closed, "the connection that was already open is not affected"

# ---- nobody listening / not a helper / no code set
try:
    RL.Link("127.0.0.1", 1, "ABCD-EFGH-JKMN", timeout=2).connect(); raise SystemExit("connected to nothing")
except RL.RemoteError as e:
    assert "does not answer" in str(e) and "helper running" in str(e), str(e)
hp0 = helper({})
try:
    RL.Link("127.0.0.1", hp0.port, "ABCD-EFGH-JKMN").connect(); raise SystemExit("no code set, but got in")
except RL.RemoteError as e:
    assert "No access code is set" in str(e), str(e)
hp0.stop()
hp2 = helper(cfg_p)                                            # a code stored the other way works the same
l2 = RL.Link("127.0.0.1", hp2.port, "ABCDEFGHJKMN").connect(); assert l2.info["helper"] == H.HELPER_VERSION; l2.close(); hp2.stop()

# ---- the screen: first the whole picture, then only what changed
def paint_into(fb, h, payload):
    off = 0
    for x, y, w, hh, enc, n in h["rects"]:
        assert enc == "z"
        raw = zlib.decompress(payload[off:off + n]); off += n
        for r in range(hh):
            fb[((y + r) * h["w"] + x) * 4:((y + r) * h["w"] + x + w) * 4] = raw[r * w * 4:(r + 1) * w * 4]
h, payload = link.frame(full=True, lossy=False, wait=0)
assert (h["w"], h["h"], h["fmt"]) == (320, 200, "bgrx") and h["rects"] == [[0, 0, 320, 200, "z", len(payload)]]
fb = bytearray(320 * 200 * 4); paint_into(fb, h, payload); assert bytes(fb) == bytes(hp.screen.buf)
t0 = time.time(); h, payload = link.frame(lossy=False, wait=0.3)
assert h["rects"] == [] and payload == b"" and 0.25 < time.time() - t0 < 1.5, "nothing changed: it waits a moment and says so"
hp.screen.paint(70, 10, 20, 30, (1, 2, 3, 0)); hp.screen.paint(300, 190, 5, 5, (9, 9, 9, 0))
h, payload = link.frame(lossy=False, wait=0.3)
assert [r[:4] for r in h["rects"]] == [[64, 0, 64, 64], [256, 128, 64, 64], [256, 192, 64, 8]], h["rects"]       # 64-pixel tiles; the last row of tiles is 8 high
paint_into(fb, h, payload); assert bytes(fb) == bytes(hp.screen.buf), "the picture here equals the screen there"
hp.screen.paint(0, 0, 320, 150, (5, 6, 7, 0))                    # most of the screen: sent as one piece
h, payload = link.frame(lossy=False, wait=0)
assert [r[:4] for r in h["rects"]] == [[0, 0, 320, 200]]
paint_into(fb, h, payload); assert bytes(fb) == bytes(hp.screen.buf)
rects = H.diff_rects(b"\0" * 400, b"\0" * 396 + b"\1\0\0\0", 10, 10, 4); assert rects == [(0, 0, 10, 10)]
assert H.diff_rects(b"\0" * 400, b"\0" * 400, 10, 10, 4) == []
ppm = b"P6\n# made by grim\n640 480\n255\nDATA"
assert H.parse_ppm_header(ppm) == (640, 480, ppm.index(b"DATA"))
if hp.jpeg:                                                    # JPEG while a large part moves (video) when the helper's computer can make them
    hp.screen.paint(0, 0, 320, 200, (200, 100, 50, 0))
    h, payload = link.frame(lossy=True, wait=0)
    assert h["rects"][0][4] == "j" and payload[:2] == b"\xff\xd8"
    h, payload = link.frame(lossy=True, wait=0.3)             # it stands still now: the same part once more, exact
    assert [r[:5] for r in h["rects"]] == [[0, 0, 320, 200, "z"]]
    paint_into(fb, h, payload); assert bytes(fb) == bytes(hp.screen.buf), "a picture that stands still is exact"
    assert link.frame(lossy=True, wait=0)[0]["rects"] == []
    hp.screen.paint(3, 3, 5, 5, (0, 0, 0, 0))
    h, payload = link.frame(lossy=True, wait=0); assert [r[4] for r in h["rects"]] == ["z"], "a small change stays exact"
    paint_into(fb, h, payload); assert bytes(fb) == bytes(hp.screen.buf)

# ---- keyboard and mouse
inp = hp.inp
link.input([{"t": "move", "x": 10.5, "y": 20}, {"t": "btn", "b": 1, "down": True}, {"t": "btn", "b": 1, "down": False}, {"t": "wheel", "dy": -2}])
link.input([{"t": "key", "key": "Shift", "down": True}, {"t": "key", "key": "A", "down": True}, {"t": "key", "key": "A", "down": False},
            {"t": "key", "key": "Shift", "down": False}, {"t": "key", "key": "b", "down": True}])
link.request("ping")                                           # everything before it has been handled
assert inp.log[:5] == [("move", 10.5, 20.0, 320, 200), ("btn", 1, True), ("btn", 1, False), ("wheel", -2, 0), ("flush",)], inp.log[:6]
assert inp.log[5:11] == [("key", "Shift", True), ("key", "a", True), ("key", "a", False), ("key", "Shift", False), ("key", "b", True), ("flush",)]
del inp.log[:]
link.input([{"t": "text", "s": "Hi\n"}]); link.request("ping")
assert inp.log == [("key", "SHIFT", True), ("key", "h", True), ("key", "SHIFT", False), ("key", "h", False), ("key", "i", True), ("key", "i", False),
                   ("key", "Return", True), ("key", "Return", False), ("flush",)], inp.log
del inp.log[:]
link.input([{"t": "release"}]); link.request("ping")
assert ("key", "b", False) in inp.log, "keys still held are let go"
u = H.LINUX_CHARS; assert u["a"] == (30, False) and u["A"] == (30, True) and u["!"] == (2, True) and u["/"] == (53, False) and u["?"] == (53, True)
assert H.KEYSYMS["F1"] == 0xffbe and H.KEYSYMS["F12"] == 0xffc9 and H.WIN_VK["F1"] == 0x70 and H.LINUX_KEYS["F10"] == 68 and H.LINUX_KEYS["F1"] == 59

# ---- files
D = tempfile.mkdtemp(prefix="opara_rf_")
big = os.path.join(D, "big.bin"); open(big, "wb").write(os.urandom(H.CHUNK * 2 + 12345))
empty = os.path.join(D, "empty.txt"); open(empty, "wb").close()
exact = os.path.join(D, "exact.bin"); open(exact, "wb").write(os.urandom(H.CHUNK))
prog = []
for f in (big, empty, exact):
    n = link.upload(f, link.join(D, "there", os.path.basename(f)), lambda d, t: prog.append((d, t)))
    assert n == os.path.getsize(f) and open(f, "rb").read() == open(os.path.join(D, "there", os.path.basename(f)), "rb").read()
assert prog[0][1] == os.path.getsize(big) and (os.path.getsize(big), os.path.getsize(big)) in prog
assert not [f for f in os.listdir(os.path.join(D, "there")) if f.endswith(".part")]
assert abs(os.path.getmtime(os.path.join(D, "there", "big.bin")) - os.path.getmtime(big)) < 1, "the file keeps its date"
assert link.file_hash(link.join(D, "there", "big.bin")) == hashlib.sha256(open(big, "rb").read()).hexdigest()
n = link.download(link.join(D, "there", "big.bin"), os.path.join(D, "back", "big.bin"))
assert n == os.path.getsize(big) and open(big, "rb").read() == open(os.path.join(D, "back", "big.bin"), "rb").read()
r = link.ls(link.join(D, "there"))
assert r["path"] == os.path.join(D, "there") and r["parent"] == D and [e[0] for e in r["entries"]] == ["big.bin", "empty.txt", "exact.bin"]
assert link.ls(D)["entries"][0][:2] == ["back", True], "folders first"
link.mkdir(link.join(D, "new", "deep")); assert os.path.isdir(os.path.join(D, "new", "deep"))
link.rename(link.join(D, "there", "empty.txt"), link.join(D, "there", "renamed.txt")); assert os.path.exists(os.path.join(D, "there", "renamed.txt"))
try:
    link.rename(link.join(D, "there", "renamed.txt"), link.join(D, "there", "big.bin")); raise SystemExit("renamed over a file")
except RL.RemoteError as e:
    assert "already there" in str(e)
link.delete(link.join(D, "there", "renamed.txt")); assert not os.path.exists(os.path.join(D, "there", "renamed.txt"))
try:
    link.delete(link.join(D, "new")); raise SystemExit("deleted a folder with things in it without being asked to")
except RL.RemoteError:
    pass
link.delete(link.join(D, "new"), recursive=True); assert not os.path.exists(os.path.join(D, "new"))
try:
    link.download(link.join(D, "nope.bin"), os.path.join(D, "x.bin")); raise SystemExit("downloaded a file that is not there")
except RL.RemoteError as e:
    assert "No such file" in str(e) or "cannot find the file" in str(e), str(e)          # the other system's own words (Linux / Windows)
assert not os.path.exists(os.path.join(D, "x.bin")) and not os.path.exists(os.path.join(D, "x.bin.part"))
assert link.stat(link.join(D, "nope.bin"))["exists"] is False and link.stat(big)["size"] == os.path.getsize(big)
assert link.read_file(big)[:100] == open(big, "rb").read()[:100]
link.write_file(link.join(D, "small.json"), b'{"a": 1}'); assert open(os.path.join(D, "small.json"), "rb").read() == b'{"a": 1}'
assert link.find("BIG.BIN", [D], 3) == [os.path.join(D, "back", "big.bin"), os.path.join(D, "big.bin"), os.path.join(D, "there", "big.bin")] or \
       sorted(link.find("BIG.BIN", [D], 3)) == sorted([os.path.join(D, "back", "big.bin"), os.path.join(D, "big.bin"), os.path.join(D, "there", "big.bin")])
assert link.disk(D)["free"] > 0
# a folder, both ways; a second download copies nothing again
T = os.path.join(D, "tree"); os.makedirs(os.path.join(T, "a", "b")); open(os.path.join(T, "one.txt"), "w").write("1"); open(os.path.join(T, "a", "b", "two.txt"), "w").write("22")
assert link.upload_tree(T, link.join(D, "tree_there")) == 2 and open(os.path.join(D, "tree_there", "a", "b", "two.txt")).read() == "22"
assert link.walk(link.join(D, "tree_there")) and [f[0] for f in link.walk(link.join(D, "tree_there"))] == ["a/b/two.txt", "one.txt"]
seen = []
assert link.download_tree(link.join(D, "tree_there"), os.path.join(D, "tree_back"), lambda d, t, n: seen.append((d, t, n))) == (2, 0)
assert seen[-1][:2] == (3, 3) and link.download_tree(link.join(D, "tree_there"), os.path.join(D, "tree_back")) == (0, 2)
# stopping a copy leaves nothing half-written on either side
calls = [0]
def stop_soon():
    calls[0] += 1; return calls[0] > 1
try:
    link.upload(big, link.join(D, "stopped.bin"), stop=stop_soon); raise SystemExit("not stopped")
except RL.Stopped:
    pass
link.request("ping"); time.sleep(0.1)
assert not os.path.exists(os.path.join(D, "stopped.bin")) and not os.path.exists(os.path.join(D, "stopped.bin.part"))
calls = [0]
try:
    link.download(big, os.path.join(D, "stopped2.bin"), stop=stop_soon); raise SystemExit("not stopped")
except RL.Stopped:
    pass
assert not os.path.exists(os.path.join(D, "stopped2.bin")) and not os.path.exists(os.path.join(D, "stopped2.bin.part"))

# ---- commands
py = sys.executable
def run(cmd, **kw):
    code, out = link.run(cmd, **kw)
    return code, out.replace("\r\n", "\n")
assert run(f'"{py}" -c "print(6*7)"') == (0, "42\n")
code, out = run(f'"{py}" -c "import sys; print(\'out\'); sys.stderr.write(\'err\\n\'); sys.exit(3)"'); assert code == 3 and "out" in out and "err" in out
assert os.path.samefile(run(f'"{py}" -c "import os; print(os.getcwd())"', cwd=D)[1].strip(), D), "a command runs in the folder it was given"
got, done = [], threading.Event()
rid = link.spawn(f'"{py}" -u -c "import sys; print(\'ready\'); sys.stdout.flush(); print(sys.stdin.readline().strip().upper())"',
                 on_out=got.append, on_done=lambda code, stopped: (got.append((code, stopped)), done.set()))
for _ in range(100):
    if "ready" in "".join(g for g in got if isinstance(g, str)): break
    time.sleep(0.05)
link.write_in(rid, "typed in\n"); assert done.wait(10) and got[-1] == (0, False) and "TYPED IN" in "".join(g for g in got if isinstance(g, str))
got, done = [], threading.Event()
rid = link.spawn(f'"{py}" -c "import time; time.sleep(60)"', on_out=got.append, on_done=lambda code, stopped: (got.append((code, stopped)), done.set()))
time.sleep(0.4); link.kill(rid); assert done.wait(10) and got[-1][1] is True, got
t0 = time.time(); code, out = link.run(f'"{py}" -c "import time; time.sleep(60)"', timeout=1); assert time.time() - t0 < 10 and code != 0
pid = link.launch(f'"{py}" -c "open(r\'{os.path.join(D, "launched.txt")}\', \'w\').write(\'x\')"'); assert isinstance(pid, int)
for _ in range(100):
    if os.path.exists(os.path.join(D, "launched.txt")): break
    time.sleep(0.05)
assert os.path.exists(os.path.join(D, "launched.txt")), "a launched program runs on its own"
try:
    link.request("no_such_thing"); raise SystemExit("an unknown request was answered")
except RL.RemoteError as e:
    assert "does not know" in str(e)

# ---- the connection is gone: said once, in words; later calls say so too
closed = []
link.on_closed = closed.append
hp.stop(); time.sleep(0.5)
assert link.closed and closed and "was lost" in closed[0] and "Test Pi" in closed[0], closed
try:
    link.ls(D); raise SystemExit("answered after the connection was gone")
except RL.LinkClosed:
    pass

# ---- parts switched off on the other computer
hp3 = helper(dict(cfg, allow_input=False, allow_files=False, allow_commands=False))
l3 = RL.Link("127.0.0.1", hp3.port, "ABCD-EFGH-JKMN").connect()
assert l3.info["input"]["ok"] is False and "switched off" in l3.info["input"]["why"] and l3.info["files"] is False and l3.info["commands"] is False
l3.input([{"t": "move", "x": 1, "y": 1}]); l3.request("ping"); assert hp3.inp.log == []
for fn, a in ((l3.ls, (D,)), (l3.run, ("echo hi",)), (l3.upload, (big, os.path.join(D, "no.bin")))):
    try:
        fn(*a); raise SystemExit("a switched-off part answered")
    except RL.RemoteError as e:
        assert "switched off on that computer" in str(e), str(e)
assert l3.frame(full=True, lossy=False, wait=0)[0]["w"] == 320
l3.close(); hp3.stop()
hp4 = helper(dict(cfg, allow_screen=False)); l4 = RL.Link("127.0.0.1", hp4.port, "ABCD-EFGH-JKMN").connect()
assert l4.info["screen"]["ok"] is False
try:
    l4.frame(full=True); raise SystemExit("the screen was shown although it is switched off")
except RL.RemoteError as e:
    assert "switched off" in str(e)
l4.close(); hp4.stop()

# ---- asking on the other screen: a No there is told here
asked = []
H.ask_on_screen = lambda text: (asked.append(text), False)[1]
hp5 = helper(dict(cfg, ask=True))
try:
    RL.Link("127.0.0.1", hp5.port, "ABCD-EFGH-JKMN", name="Tester").connect(); raise SystemExit("refused on the screen, but got in")
except RL.RemoteError as e:
    assert "refused on that computer's screen" in str(e) and "Tester (127.0.0.1) wants to see and use this computer" in asked[0]
H.ask_on_screen = lambda text: True
l5 = RL.Link("127.0.0.1", hp5.port, "ABCD-EFGH-JKMN").connect(); assert l5.info["name"] == "Test Pi"; l5.close(); hp5.stop()

# ---- searching the network
udp_port = 47000 + os.getpid() % 900
hp6 = H.Helper(dict(cfg, discovery_port=udp_port), port=0, bind="127.0.0.1").start()
found = RL.discover(1.0, port=udp_port, extra=["127.0.0.1"])
assert [(f["name"], f["port"], f["helper"]) for f in found] == [("Test Pi", hp6.port, H.HELPER_VERSION)], found       # once, whatever address answered
hp6.stop()

# ---- the saved computers
assert RL.load_computers() == []
RL.remember("Pi", "192.168.1.9"); RL.remember("Laptop", "192.168.1.7", 47800, "CODE1234")
assert [c["name"] for c in RL.load_computers()] == ["Laptop", "Pi"] and "code" not in RL.load_computers()[1]
RL.remember("Pi 5", "192.168.1.9"); assert [c["name"] for c in RL.load_computers()] == ["Pi 5", "Laptop"]
RL.forget("192.168.1.7"); assert [c["host"] for c in RL.load_computers()] == ["192.168.1.9"]

# ---- the command line: a first start makes a code; --status; switches are remembered
import io, contextlib
os.environ["OPRH_CONFIG_DIR"] = tempfile.mkdtemp(prefix="opara_rh2_")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    assert H.main(["--new-code", "--status", "--no-commands", "--name", "Bench laptop"]) == 0
text = buf.getvalue()
assert "Access code:" in text and "Bench laptop" in text and "commands" not in text.split("Allowed:")[1] and "files" in text.split("Allowed:")[1]
code = text.split("Access code:")[1].split()[0]
c7 = H.load_config(); assert c7["allow_commands"] is False and c7["name"] == "Bench laptop"
hp7 = helper(c7); l7 = RL.Link("127.0.0.1", hp7.port, code).connect(); assert l7.info["name"] == "Bench laptop"; l7.close(); hp7.stop()
with contextlib.redirect_stdout(io.StringIO()):
    assert H.main(["--code", "short"]) == 2

# ---- the real screen, keyboard and mouse of an X11 desktop (the test runs under one)
if os.environ.get("DISPLAY") and sys.platform.startswith("linux") and not H.is_wayland():
    scr = H.make_screen()
    w, h, bpp, fmt, data = scr.grab()
    assert scr.name == "X11" and w > 100 and h > 100 and bpp == 4 and fmt == "bgrx" and len(data) == w * h * 4
    xi = H.make_input()
    assert xi.name == "X11"
    H.apply_events(xi, [{"t": "move", "x": 123, "y": 77}], w, h)
    x11 = H._xlib()
    x11.XQueryPointer.argtypes = [H.ctypes.c_void_p, H.ctypes.c_ulong] + [H.ctypes.c_void_p] * 7
    d = x11.XOpenDisplay(None)
    out = [H.ctypes.c_ulong(), H.ctypes.c_ulong(), H.ctypes.c_int(), H.ctypes.c_int(), H.ctypes.c_int(), H.ctypes.c_int(), H.ctypes.c_uint()]
    time.sleep(0.2)
    x11.XQueryPointer(d, x11.XDefaultRootWindow(d), *[H.ctypes.byref(v) for v in out])
    assert (out[2].value, out[3].value) == (123, 77), (out[2].value, out[3].value)
    assert xi.lookup("a")[1] is False and xi.lookup("A")[1] is True and xi.lookup("Return")[1] is None and xi.lookup("no such key") is None
    assert xi.lookup("€") is not None, "a character the layout has no key for gets a spare key"
    H.apply_events(xi, [{"t": "key", "key": "Shift", "down": True}, {"t": "key", "key": "Shift", "down": False}, {"t": "wheel", "dy": 1}], w, h)
    print("X11 back ends: ok", flush=True)
else:
    print("X11 back ends: skipped (no X11 desktop here)", flush=True)

for d in (CFG, D, os.environ["OPARA_USER_DIR"], os.environ["OPRH_CONFIG_DIR"]):
    shutil.rmtree(d, ignore_errors=True)
print("OK remote link", flush=True)
os._exit(0)
