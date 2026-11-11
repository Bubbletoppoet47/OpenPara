#!/usr/bin/env python3
"""
openpara_remote_helper.py - lets OpenPara (the Remote Computer add-on) see and use THIS computer over the local network.

Run it on the computer you want to reach (a Raspberry Pi, a laptop whose screen is broken ...):

    python3 openpara_remote_helper.py              start it; the first time it makes an access code and shows it
    python3 openpara_remote_helper.py --install    copy it to this computer and start it with every login
    python3 openpara_remote_helper.py --new-code   make a new access code (the old one stops working)
    python3 openpara_remote_helper.py --check      say what works on this computer (screen, keyboard and mouse)
    python3 openpara_remote_helper.py --help       every option

What it allows, and only to someone who knows the access code: seeing the screen, using the keyboard and mouse, copying files to and from
this computer, and running commands as the user who started it.  That is full control of this account, so:
    * only run it on a computer of your own, on a network you trust (home Wi-Fi, your own hotspot) - never open its port to the internet;
    * keep the access code to yourself; --new-code replaces it, --uninstall removes the autostart;
    * every connection is written to connections.log in its settings folder, and --ask makes it ask on this screen before each one;
    * --no-input / --no-files / --no-commands / --no-screen switch a part off.

It needs nothing but Python 3.8+ (one file, standard library only).  Screen and keyboard/mouse use what the system has:
    Windows                 built in
    Linux with X11          libX11 / libXtst (there on any desktop)
    Linux with Wayland      'grim' for the screen (Raspberry Pi OS has it) and /dev/uinput for keyboard and mouse (--install sets that up)
If OpenCV or Pillow is installed the screen is also sent as JPEG, which is much lighter for video.

How the connection is protected: both sides prove they know the access code with SPAKE2 (so a listener, or a wrong guess, learns nothing
to try codes against offline), and everything after that is encrypted and checked (SHAKE-256 stream + HMAC-SHA256).  Wrong codes are
counted and the address is locked out for a while.  It is written from standard parts but has not had a security review: local network only.
"""
import argparse
import ctypes
import ctypes.util
import errno
import getpass
import hashlib
import hmac
import json
import os
import platform
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib

PROTO = 1
HELPER_VERSION = "1.1"
PORT = 47800
DISCOVERY_PORT = 47801
MAGIC = b"OPRH1"
DISCOVER = b"OPRH-DISCOVER1"
MAX_MSG = 96 * 1024 * 1024          # one message (a full 4K frame fits)
PLAIN_MAX = 16384                   # a message before the code is proven
CHUNK = 256 * 1024                  # file data per message
TILE = 64
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"        # no I L O 0 1: easy to read out and type
FAIL_LIMIT, FAIL_LOCK_S = 5, 300


class RemoteError(Exception):
    """Something the person can act on (wrong code, not allowed, no such file ...); the text is shown as it is."""


class BackendError(RemoteError):
    pass


# ====================================================================================================== access code and handshake (SPAKE2)

_P_HEX = """
FFFFFFFF FFFFFFFF C90FDAA2 2168C234 C4C6628B 80DC1CD1 29024E08 8A67CC74 020BBEA6 3B139B22 514A0879 8E3404DD
EF9519B3 CD3A431B 302B0A6D F25F1437 4FE1356D 6D51C245 E485B576 625E7EC6 F44C42E9 A637ED6B 0BFF5CB6 F406B7ED
EE386BFB 5A899FA5 AE9F2411 7C4B1FE6 49286651 ECE45B3D C2007CB8 A163BF05 98DA4836 1C55D39A 69163FA8 FD24CF5F
83655D23 DCA3AD96 1C62F356 208552BB 9ED52907 7096966D 670C354E 4ABC9804 F1746C08 CA18217C 32905E46 2E36CE3B
E39E772C 180E8603 9B2783A2 EC07A28F B5C55DF0 6F4C52C9 DE2BCBF6 95581718 3995497C EA956AE5 15D22618 98FA0510
15728E5A 8AACAA68 FFFFFFFF FFFFFFFF"""
P = int("".join(_P_HEX.split()), 16)          # the 2048-bit MODP group of RFC 3526 (a safe prime); 2 generates its prime-order subgroup
G = 2


def _element(label):
    """A group element nobody knows the logarithm of: a hash, squared into the prime-order subgroup."""
    return pow(int.from_bytes(hashlib.shake_256(label).digest(256), "big") % P, 2, P)


M_EL = _element(b"OpenPara Remote SPAKE2 M")
N_EL = _element(b"OpenPara Remote SPAKE2 N")


def normalize_code(code):
    return "".join(str(code or "").split()).replace("-", "").upper()


def new_code(groups=3):
    return "-".join("".join(secrets.choice(CODE_ALPHABET) for _ in range(4)) for _ in range(groups))


def default_kdf():
    if hasattr(hashlib, "scrypt"):
        return {"name": "scrypt", "n": 16384, "r": 8, "p": 1}
    return {"name": "pbkdf2", "iter": 300000}


def derive_w(code, salt, kdf):
    """The number both sides make from the access code (slow on purpose).  Limits keep a made-up 'kdf' from tying up the client."""
    pw = normalize_code(code).encode("utf-8")
    name = kdf.get("name")
    if name == "scrypt":
        n, r, p = int(kdf.get("n", 0)), int(kdf.get("r", 0)), int(kdf.get("p", 0))
        if not (1024 <= n <= 131072 and n & (n - 1) == 0 and 1 <= r <= 16 and 1 <= p <= 4):
            raise RemoteError("The other computer asked for settings this program does not accept.")
        if not hasattr(hashlib, "scrypt"):
            raise RemoteError("This Python has no scrypt; set the code again on the other computer with --pbkdf2.")
        k = hashlib.scrypt(pw, salt=salt, n=n, r=r, p=p, dklen=32, maxmem=256 * 1024 * 1024)
    elif name == "pbkdf2":
        it = int(kdf.get("iter", 0))
        if not 100000 <= it <= 3000000:
            raise RemoteError("The other computer asked for settings this program does not accept.")
        k = hashlib.pbkdf2_hmac("sha256", pw, salt, it, 32)
    else:
        raise RemoteError("The other computer uses a newer helper than this program understands.")
    return int.from_bytes(k, "big")


def _i2b(n):
    return n.to_bytes(256, "big")


def _mac(key, *parts):
    return hmac.new(key, b"".join(parts), hashlib.sha256).digest()


def _master(raw_c, raw_h, x_el, y_el, k_el, w):
    h = hashlib.sha256()
    for part in (raw_c, raw_h, _i2b(x_el), _i2b(y_el), _i2b(k_el), w.to_bytes(32, "big")):
        h.update(struct.pack(">I", len(part)))
        h.update(part)
    return h.digest()


def _check_element(v):
    if not 1 < v < P - 1:
        raise RemoteError("The other side sent a value that is not allowed.")
    return v


def _recvn(sock, n):
    buf = bytearray()
    while len(buf) < n:
        part = sock.recv(min(n - len(buf), 1 << 20))
        if not part:
            raise ConnectionError("The connection was closed.")
        buf += part
    return bytes(buf)


def _send_plain(sock, obj):
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    sock.sendall(struct.pack(">H", len(raw)) + raw)
    return raw


def _recv_plain(sock):
    n = struct.unpack(">H", _recvn(sock, 2))[0]
    if n > PLAIN_MAX:
        raise RemoteError("The other side sent something that is not a helper message.")
    raw = _recvn(sock, n)
    try:
        obj = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise RemoteError("The other side sent something that is not a helper message.")
    if not isinstance(obj, dict):
        raise RemoteError("The other side sent something that is not a helper message.")
    return raw, obj


def _xor(a, b):
    return (int.from_bytes(a, "little") ^ int.from_bytes(b, "little")).to_bytes(len(a), "little")


class Channel:
    """The encrypted, checked message stream after the handshake.  A message is a small JSON header plus raw bytes (a frame, file data)."""

    def __init__(self, sock, master, is_client):
        a, b = ("c2h", "h2c") if is_client else ("h2c", "c2h")
        self.sock = sock
        self.k_out, self.m_out = _mac(master, b"enc " + a.encode()), _mac(master, b"mac " + a.encode())
        self.k_in, self.m_in = _mac(master, b"enc " + b.encode()), _mac(master, b"mac " + b.encode())
        self.n_out = self.n_in = 0
        self.lock = threading.Lock()
        self.sent = self.received = 0

    def send(self, header, payload=b""):
        hj = json.dumps(header, separators=(",", ":")).encode("utf-8")
        plain = struct.pack(">I", len(hj)) + hj + bytes(payload)
        if len(plain) > MAX_MSG:
            raise RemoteError("That is too much for one message.")
        with self.lock:
            seq = struct.pack(">Q", self.n_out)
            self.n_out += 1
            ct = _xor(plain, hashlib.shake_256(self.k_out + seq).digest(len(plain)))
            ln = struct.pack(">I", len(ct))
            self.sock.sendall(ln + ct + _mac(self.m_out, seq, ln, ct)[:16])
            self.sent += len(ct) + 20

    def recv(self):
        n = struct.unpack(">I", _recvn(self.sock, 4))[0]
        if n > MAX_MSG or n < 4:
            raise ConnectionError("The connection is out of step.")
        body = _recvn(self.sock, n + 16)
        ct, tag = body[:n], body[n:]
        seq = struct.pack(">Q", self.n_in)
        if not hmac.compare_digest(tag, _mac(self.m_in, seq, struct.pack(">I", n), ct)[:16]):
            raise ConnectionError("A message was damaged or changed on the way.")
        self.n_in += 1
        self.received += n + 20
        plain = _xor(ct, hashlib.shake_256(self.k_in + seq).digest(n))
        hl = struct.unpack(">I", plain[:4])[0]
        if hl > n - 4:
            raise ConnectionError("The connection is out of step.")
        return json.loads(plain[4:4 + hl].decode("utf-8")), plain[4 + hl:]

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def client_handshake(sock, code, client_name):
    """The asking side.  Returns (Channel, what the helper said about itself).  Raises RemoteError with plain words when the code is wrong."""
    sock.sendall(MAGIC)
    raw_c = _send_plain(sock, {"v": PROTO, "name": str(client_name)[:60]})
    raw_h, h = _recv_plain(sock)
    if h.get("error"):
        raise RemoteError(str(h["error"]))
    try:
        salt, y_el = bytes.fromhex(h["salt"]), _check_element(int(h["Y"], 16))
        w = derive_w(code, salt, h["kdf"])
    except (KeyError, ValueError, TypeError):
        raise RemoteError("The other computer answered, but not like an OpenPara helper.")
    x = (1 << 255) | secrets.randbits(255)
    x_el = pow(G, x, P) * pow(M_EL, w, P) % P
    k_el = pow(y_el * pow(N_EL, -w, P) % P, 2 * x, P)
    if k_el in (0, 1):
        raise RemoteError("The other side sent a value that is not allowed.")
    master = _master(raw_c, raw_h, x_el, y_el, k_el, w)
    _send_plain(sock, {"X": "%x" % x_el, "confirm": _mac(master, b"client knows the code").hex()})
    _, r = _recv_plain(sock)
    if r.get("error"):
        raise RemoteError(str(r["error"]))
    if not hmac.compare_digest(bytes.fromhex(str(r.get("confirm", ""))), _mac(master, b"helper knows the code")):
        raise RemoteError("The other computer could not show that it knows the access code. Not connected.")
    return Channel(sock, master, True), {k: h.get(k) for k in ("name", "platform", "helper", "v")}


def host_handshake(sock, cfg, peer_ip, guard):
    """The helper's side.  Returns (Channel, the client's name) or raises; a wrong code is counted against peer_ip in guard."""
    if _recvn(sock, len(MAGIC)) != MAGIC:
        raise RemoteError("not a helper client")
    raw_c, c = _recv_plain(sock)
    wait = guard.locked(peer_ip)
    if wait:
        _send_plain(sock, {"error": f"Too many wrong access codes from this computer. Try again in {max(1, round(wait / 60))} minute(s)."})
        raise RemoteError("locked out")
    if not cfg.get("w"):
        _send_plain(sock, {"error": "No access code is set on that computer yet. Start the helper there once to make one."})
        raise RemoteError("no code set")
    w = int(cfg["w"], 16)
    y = (1 << 255) | secrets.randbits(255)
    y_el = pow(G, y, P) * pow(N_EL, w, P) % P
    raw_h = _send_plain(sock, {"v": PROTO, "name": cfg.get("name") or socket.gethostname(), "platform": sys.platform, "helper": HELPER_VERSION,
                               "salt": cfg["salt"], "kdf": cfg["kdf"], "Y": "%x" % y_el})
    _, r = _recv_plain(sock)
    try:
        x_el = _check_element(int(r["X"], 16))
        confirm = bytes.fromhex(r["confirm"])
    except (KeyError, ValueError, TypeError):
        raise RemoteError("bad client message")
    k_el = pow(x_el * pow(M_EL, -w, P) % P, 2 * y, P)
    master = _master(raw_c, raw_h, x_el, y_el, k_el, w)
    if k_el in (0, 1) or not hmac.compare_digest(confirm, _mac(master, b"client knows the code")):
        guard.failed(peer_ip)
        time.sleep(1.0)
        _send_plain(sock, {"error": "Wrong access code."})
        raise RemoteError("wrong code")
    guard.ok(peer_ip)
    _send_plain(sock, {"confirm": _mac(master, b"helper knows the code").hex()})
    return Channel(sock, master, False), str(c.get("name") or "?")[:60]


class Guard:
    """Counts wrong access codes per address; after FAIL_LIMIT in a row the address waits FAIL_LOCK_S."""

    def __init__(self):
        self.lock = threading.Lock()
        self.fails = {}                      # ip -> [count, locked until]

    def locked(self, ip):
        with self.lock:
            f = self.fails.get(ip)
            return max(0.0, f[1] - time.time()) if f and f[1] > time.time() else 0.0

    def failed(self, ip):
        with self.lock:
            f = self.fails.setdefault(ip, [0, 0.0])
            f[0] += 1
            if f[0] >= FAIL_LIMIT:
                f[0], f[1] = 0, time.time() + FAIL_LOCK_S

    def ok(self, ip):
        with self.lock:
            self.fails.pop(ip, None)


# ====================================================================================================== settings of the helper

def config_dir():
    d = os.environ.get("OPRH_CONFIG_DIR")
    if not d:
        if os.name == "nt":
            d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "OpenParaRemote")
        else:
            d = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "openpara-remote")
    os.makedirs(d, exist_ok=True)
    return d


def load_config():
    try:
        with open(os.path.join(config_dir(), "config.json"), encoding="utf-8") as f:
            c = json.load(f)
        if isinstance(c, dict):
            return c
    except (OSError, ValueError):
        pass
    return {}


def save_config(cfg):
    path = os.path.join(config_dir(), "config.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    try:
        os.chmod(tmp, 0o600)                     # what is stored can stand in for the code: only this user reads it
    except OSError:
        pass
    os.replace(tmp, path)


def set_code(cfg, code, kdf=None):
    """Stores what the helper needs to check the code (not the code itself)."""
    if len(normalize_code(code)) < 8:
        raise RemoteError("An access code needs at least 8 letters or digits.")
    salt = secrets.token_bytes(16)
    kdf = kdf or default_kdf()
    cfg.update(salt=salt.hex(), kdf=kdf, w="%x" % derive_w(code, salt, kdf))
    return cfg


def log(text):
    line = time.strftime("%Y-%m-%d %H:%M:%S  ") + text
    try:
        with open(os.path.join(config_dir(), "connections.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    try:
        print(line, flush=True)
    except Exception:  # noqa: BLE001  (no console: started with pythonw)
        pass


SO_BINDTODEVICE = 25


def interfaces():
    """The network ports of this computer as [(number, name)], e.g. [(1, 'lo'), (2, 'eth0'), (3, 'wlan0')] (Linux); [] where they
    cannot be listed."""
    if not sys.platform.startswith("linux"):
        return []
    try:
        return list(socket.if_nameindex())
    except (OSError, AttributeError):
        return []


def interface_addresses():
    """[(port name, IPv4 address, netmask)] of the network ports that have an address (Linux, without the loopback); [] elsewhere."""
    names = [n for _i, n in interfaces()]
    if not names:
        return []
    import fcntl
    out = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for name in names:
            req = struct.pack("256s", name.encode("utf-8")[:15])
            try:
                ip = socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, req)[20:24])            # SIOCGIFADDR
                mask = socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x891b, req)[20:24])          # SIOCGIFNETMASK
            except OSError:
                continue
            if not ip.startswith("127."):
                out.append((name, ip, mask))
    finally:
        s.close()
    return out


def local_addresses():
    """This computer's addresses on its networks.  The one its normal traffic uses (the Wi-Fi of a Raspberry Pi whose wired port goes to
    an instrument) comes first: that is the one to type on the other computer."""
    out = []
    for target in ("8.8.8.8", "192.168.1.1", "10.0.0.1"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 9))
            ip = s.getsockname()[0]
            if ip not in out and not ip.startswith("127.") and target == "8.8.8.8":
                out.append(ip)
        except OSError:
            pass
        finally:
            s.close()
    for _name, ip, _mask in interface_addresses():
        if ip not in out:
            out.append(ip)
    if not out:                                                       # no default route, and not Linux: what a nearby address would use
        for target in ("192.168.1.1", "10.0.0.1"):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect((target, 9))
                ip = s.getsockname()[0]
                if ip not in out and not ip.startswith("127.") and ip != "0.0.0.0":
                    out.append(ip)
            except OSError:
                pass
            finally:
                s.close()
    return out


def describe_addresses():
    """'192.168.1.57 (wlan0), 192.168.1.2 (eth0)' - the address to use first."""
    names = {ip: name for name, ip, _m in interface_addresses()}
    return ", ".join(ip + (f" ({names[ip]})" if ip in names else "") for ip in local_addresses())


# ====================================================================================================== the screen

def _find_lib(name, fallback):
    return ctypes.util.find_library(name) or fallback


class _XImage(ctypes.Structure):
    _fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int), ("xoffset", ctypes.c_int), ("format", ctypes.c_int),
                ("data", ctypes.c_void_p), ("byte_order", ctypes.c_int), ("bitmap_unit", ctypes.c_int), ("bitmap_bit_order", ctypes.c_int),
                ("bitmap_pad", ctypes.c_int), ("depth", ctypes.c_int), ("bytes_per_line", ctypes.c_int), ("bits_per_pixel", ctypes.c_int),
                ("red_mask", ctypes.c_ulong), ("green_mask", ctypes.c_ulong), ("blue_mask", ctypes.c_ulong)]


def _xlib():
    x = ctypes.CDLL(_find_lib("X11", "libX11.so.6"))
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
    x.XGetImage.restype = ctypes.POINTER(_XImage)
    x.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
    x.XDestroyImage.argtypes = [ctypes.POINTER(_XImage)]
    x.XFlush.argtypes = [ctypes.c_void_p]
    x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x.XKeysymToKeycode.restype = ctypes.c_ubyte
    x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x.XkbKeycodeToKeysym.restype = ctypes.c_ulong
    x.XkbKeycodeToKeysym.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_uint]
    x.XDisplayKeycodes.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    x.XChangeKeyboardMapping.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_ulong), ctypes.c_int]
    return x


class X11Screen:
    name = "X11"

    def __init__(self):
        try:
            self.x = _xlib()
        except OSError as e:
            raise BackendError(f"The X11 library is missing here ({e}).")
        self.d = self.x.XOpenDisplay(None)
        if not self.d:
            raise BackendError("No desktop to show: start the helper from the desktop session (it needs DISPLAY).")
        self.root = self.x.XDefaultRootWindow(self.d)

    def grab(self):
        attrs = ctypes.create_string_buffer(256)
        self.x.XGetWindowAttributes(self.d, self.root, attrs)
        _x, _y, w, h = struct.unpack_from("iiii", attrs.raw, 0)
        img = self.x.XGetImage(self.d, self.root, 0, 0, w, h, ctypes.c_ulong(-1).value, 2)        # AllPlanes, ZPixmap
        if not img:
            raise BackendError("The screen could not be read.")
        try:
            im = img.contents
            bpp = im.bits_per_pixel // 8
            if bpp not in (3, 4):
                raise BackendError(f"This screen uses {im.bits_per_pixel} bits per pixel, which the helper cannot send.")
            data = ctypes.string_at(im.data, im.bytes_per_line * im.height)
            if im.bytes_per_line != im.width * bpp:
                st, row = im.bytes_per_line, im.width * bpp
                data = b"".join(data[r * st:r * st + row] for r in range(im.height))
            return im.width, im.height, bpp, "bgrx" if bpp == 4 else "bgr", data
        finally:
            self.x.XDestroyImage(img)


class GrimScreen:
    """Wayland desktops built on wlroots (Raspberry Pi OS: labwc / wayfire) let 'grim' read the screen."""
    name = "Wayland (grim)"

    def __init__(self):
        if not shutil.which("grim"):
            raise BackendError("This desktop uses Wayland and 'grim' is not installed. On the other computer run:  sudo apt install grim")
        self.grab()

    def grab(self):
        try:
            r = subprocess.run(["grim", "-t", "ppm", "-"], capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as e:
            raise BackendError(f"grim could not read the screen ({e}).")
        if r.returncode != 0 or not r.stdout.startswith(b"P6"):
            why = r.stderr.decode("utf-8", "replace").strip()[:200]
            raise BackendError("This Wayland desktop does not let grim read the screen" + (f" ({why})" if why else "") +
                               ". Switching the desktop to X11 (on a Raspberry Pi: raspi-config > Advanced > Wayland > X11) works.")
        w, h, off = parse_ppm_header(r.stdout)
        return w, h, 3, "rgb", r.stdout[off:off + w * h * 3]


def parse_ppm_header(data):
    """(width, height, offset of the pixels) of a binary PPM with 255 levels."""
    vals, i, n = [], 2, len(data)
    while len(vals) < 3:
        while i < n and data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while i < n and data[i:i + 1] != b"\n":
                i += 1
            continue
        j = i
        while j < n and not data[j:j + 1].isspace():
            j += 1
        vals.append(int(data[i:j]))
        i = j
    if vals[2] != 255:
        raise BackendError("Unexpected picture format from grim.")
    return vals[0], vals[1], i + 1


class WinScreen:
    name = "Windows"

    def __init__(self):
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        try:
            u.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass
        vp = ctypes.c_void_p
        u.GetDC.restype, u.GetDC.argtypes = vp, [vp]
        u.ReleaseDC.argtypes = [vp, vp]
        g.CreateCompatibleDC.restype, g.CreateCompatibleDC.argtypes = vp, [vp]
        g.CreateCompatibleBitmap.restype, g.CreateCompatibleBitmap.argtypes = vp, [vp, ctypes.c_int, ctypes.c_int]
        g.SelectObject.restype, g.SelectObject.argtypes = vp, [vp, vp]
        g.BitBlt.argtypes = [vp, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, vp, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        g.GetDIBits.argtypes = [vp, vp, ctypes.c_uint, ctypes.c_uint, vp, vp, ctypes.c_uint]
        g.DeleteObject.argtypes = [vp]
        g.DeleteDC.argtypes = [vp]
        self.u, self.g = u, g

    def grab(self):
        u, g = self.u, self.g
        w, h = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        hdc = u.GetDC(None)
        mem = g.CreateCompatibleDC(hdc)
        bmp = g.CreateCompatibleBitmap(hdc, w, h)
        old = g.SelectObject(mem, bmp)
        try:
            if not g.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, 0x00CC0020 | 0x40000000):                 # SRCCOPY | CAPTUREBLT
                raise BackendError("The screen could not be read (is it locked?).")
            bmi = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)                  # BITMAPINFOHEADER, top-down 32-bit
            buf = ctypes.create_string_buffer(w * h * 4)
            g.GetDIBits(mem, bmp, 0, h, buf, ctypes.create_string_buffer(bmi + b"\0" * 16), 0)
            return w, h, 4, "bgrx", buf.raw
        finally:
            g.SelectObject(mem, old)
            g.DeleteObject(bmp)
            g.DeleteDC(mem)
            u.ReleaseDC(None, hdc)


def is_wayland():
    return bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def make_screen():
    if sys.platform == "win32":
        return WinScreen()
    if sys.platform == "darwin":
        raise BackendError("Showing the screen of a Mac is not supported yet (files and commands work).")
    return GrimScreen() if is_wayland() else X11Screen()


def diff_rects(new, old, w, h, bpp):
    """[(x, y, w, h)] of what changed between two frames of the same size, as runs of 64-pixel tiles; one whole-screen rect when most of it did."""
    stride = w * bpp
    rects, changed = [], 0
    for by in range(0, h, TILE):
        bh = min(TILE, h - by)
        a = by * stride
        if new[a:a + bh * stride] == old[a:a + bh * stride]:
            continue
        run = None
        for tx in range(0, w, TILE):
            c0, c1 = tx * bpp, min(tx + TILE, w) * bpp
            dirty = False
            for r in range(bh):
                o = a + r * stride
                if new[o + c0:o + c1] != old[o + c0:o + c1]:
                    dirty = True
                    break
            if dirty:
                run = [tx, min(tx + TILE, w)] if run is None else [run[0], min(tx + TILE, w)]
            elif run is not None:
                rects.append((run[0], by, run[1] - run[0], bh))
                changed += (run[1] - run[0]) * bh
                run = None
        if run is not None:
            rects.append((run[0], by, run[1] - run[0], bh))
            changed += (run[1] - run[0]) * bh
    if changed > 0.6 * w * h:
        return [(0, 0, w, h)]
    return rects


def covers(a, b):
    """Whether rect a covers rect b whole."""
    return a[0] <= b[0] and a[1] <= b[1] and a[0] + a[2] >= b[0] + b[2] and a[1] + a[3] >= b[1] + b[3]


def cut_rect(frame, w, bpp, rect):
    x, y, rw, rh = rect
    stride = w * bpp
    if x == 0 and rw == w:
        return frame[y * stride:(y + rh) * stride]
    return b"".join(frame[(y + r) * stride + x * bpp:(y + r) * stride + (x + rw) * bpp] for r in range(rh))


def jpeg_encoder():
    """fn(raw, w, h, fmt, quality) -> JPEG bytes, from OpenCV or Pillow when one of them is installed here, else None."""
    try:
        import cv2
        import numpy as np

        def enc(raw, w, h, fmt, q):
            a = np.frombuffer(raw, np.uint8).reshape(h, w, len(fmt))
            a = a[:, :, 2::-1] if fmt == "rgb" else a[:, :, :3]
            ok, out = cv2.imencode(".jpg", np.ascontiguousarray(a), [cv2.IMWRITE_JPEG_QUALITY, int(q)])
            if not ok:
                raise ValueError("jpeg")
            return out.tobytes()
        return enc
    except Exception:  # noqa: BLE001  (not installed, or a broken install)
        pass
    try:
        import io
        from PIL import Image

        def enc(raw, w, h, fmt, q):
            im = Image.frombuffer("RGB", (w, h), raw, "raw", {"bgrx": "BGRX", "bgr": "BGR", "rgb": "RGB"}[fmt], 0, 1)
            b = io.BytesIO()
            im.save(b, "JPEG", quality=int(q))
            return b.getvalue()
        return enc
    except Exception:  # noqa: BLE001
        return None


# ====================================================================================================== keyboard and mouse

KEYSYMS = {"Return": 0xff0d, "Escape": 0xff1b, "BackSpace": 0xff08, "Tab": 0xff09, "Delete": 0xffff, "Insert": 0xff63, "Home": 0xff50,
           "End": 0xff57, "PageUp": 0xff55, "PageDown": 0xff56, "Left": 0xff51, "Up": 0xff52, "Right": 0xff53, "Down": 0xff54,
           "Shift": 0xffe1, "Control": 0xffe3, "Alt": 0xffe9, "Meta": 0xffeb, "CapsLock": 0xffe5, "Menu": 0xff67, "Print": 0xff61,
           "Pause": 0xff13, "ScrollLock": 0xff14, "NumLock": 0xff7f, "space": 0x20}
KEYSYMS.update({f"F{i}": 0xffbd + i for i in range(1, 13)})

WIN_VK = {"Return": 0x0D, "Escape": 0x1B, "BackSpace": 0x08, "Tab": 0x09, "Delete": 0x2E, "Insert": 0x2D, "Home": 0x24, "End": 0x23,
          "PageUp": 0x21, "PageDown": 0x22, "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28, "Shift": 0x10, "Control": 0x11,
          "Alt": 0x12, "Meta": 0x5B, "CapsLock": 0x14, "Menu": 0x5D, "Print": 0x2C, "Pause": 0x13, "ScrollLock": 0x91, "NumLock": 0x90,
          "space": 0x20}
WIN_VK.update({f"F{i}": 0x6F + i for i in range(1, 13)})
WIN_EXTENDED = {"Delete", "Insert", "Home", "End", "PageUp", "PageDown", "Left", "Up", "Right", "Down", "Menu", "Meta"}

LINUX_KEYS = {"Escape": 1, "BackSpace": 14, "Tab": 15, "Return": 28, "Control": 29, "Shift": 42, "Alt": 56, "space": 57, "CapsLock": 58,
              "NumLock": 69, "ScrollLock": 70, "Print": 99, "Home": 102, "Up": 103, "PageUp": 104, "Left": 105, "Right": 106, "End": 107,
              "Down": 108, "PageDown": 109, "Insert": 110, "Delete": 111, "Pause": 119, "Meta": 125, "Menu": 127, "F11": 87, "F12": 88}
LINUX_KEYS.update({f"F{i}": 58 + i for i in range(1, 11)})
_ROWS = (("1234567890-=", 2), ("qwertyuiop[]", 16), ("asdfghjkl;'`", 30), ("\\zxcvbnm,./", 43))
_SHIFTED = dict(zip("!@#$%^&*()_+{}:\"~|<>?", "1234567890-=[];'`\\,./"))
LINUX_CHARS = {}                               # char -> (key code, needs Shift) on a US keyboard
for _row, _first in _ROWS:
    for _i, _c in enumerate(_row):
        LINUX_CHARS[_c] = (_first + _i, False)
        if _c.isalpha():
            LINUX_CHARS[_c.upper()] = (_first + _i, True)
for _s, _b in _SHIFTED.items():
    LINUX_CHARS[_s] = (LINUX_CHARS[_b][0], True)
LINUX_CHARS[" "] = (57, False)
LINUX_CHARS["\n"] = (28, False)
LINUX_CHARS["\t"] = (15, False)


class _Keys:
    """What every keyboard back end shares: which keys are held, and a short Shift press when the wanted character needs the other case."""

    def __init__(self):
        self.held = {}                 # key name / char -> what was pressed for it
        self.shift = False

    def key(self, key, down):
        key = str(key)
        if key == "Shift":
            self.shift = bool(down)
        if down:
            code = self.lookup(key)
            if code is None:
                return
            self.held[key] = code
            self.press(code, True)
        else:
            code = self.held.pop(key, None)
            if code is not None:
                self.press(code, False)

    def press(self, code, down):
        raw, need_shift = code
        if down and need_shift is not None and need_shift != self.shift:
            self.raw_key(self.shift_code, need_shift)
            self.raw_key(raw, True)
            self.raw_key(self.shift_code, self.shift)
        else:
            self.raw_key(raw, down)

    def text(self, s):
        for ch in str(s):
            code = self.lookup("Return" if ch == "\n" else "Tab" if ch == "\t" else ch)
            if code is not None:
                self.press(code, True)
                self.press(code, False)

    def release_all(self):
        for key in list(self.held):
            self.key(key, False)


class X11Input(_Keys):
    name = "X11"

    def __init__(self):
        super().__init__()
        try:
            self.x = _xlib()
            self.t = ctypes.CDLL(_find_lib("Xtst", "libXtst.so.6"))
        except OSError as e:
            raise BackendError(f"Keyboard and mouse need libXtst, which is missing here ({e}). On the other computer: sudo apt install libxtst6")
        self.t.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self.t.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.t.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.t.XTestQueryExtension.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_int)] * 4
        self.d = self.x.XOpenDisplay(None)
        if not self.d:
            raise BackendError("No desktop to control: start the helper from the desktop session (it needs DISPLAY).")
        four = [ctypes.c_int() for _ in range(4)]
        if not self.t.XTestQueryExtension(self.d, *[ctypes.byref(v) for v in four]):
            raise BackendError("This X server does not allow test input (XTEST), so the keyboard and mouse cannot be used.")
        self.shift_code = self.x.XKeysymToKeycode(self.d, KEYSYMS["Shift"])
        self.spare = None

    def move(self, x, y, w, h):
        self.t.XTestFakeMotionEvent(self.d, -1, int(x), int(y), 0)

    def button(self, b, down):
        self.t.XTestFakeButtonEvent(self.d, {1: 1, 2: 3, 3: 2}.get(int(b), 1), 1 if down else 0, 0)       # ours: 1 left 2 right 3 middle

    def wheel(self, dy, dx=0):
        for n, plus, minus in ((dy, 4, 5), (dx, 7, 6)):
            for _ in range(min(abs(int(n)), 30)):
                b = plus if n > 0 else minus
                self.t.XTestFakeButtonEvent(self.d, b, 1, 0)
                self.t.XTestFakeButtonEvent(self.d, b, 0, 0)

    def lookup(self, key):
        named = key in KEYSYMS
        if named:
            sym = KEYSYMS[key]
        elif len(key) == 1:
            cp = ord(key)
            sym = cp if (0x20 <= cp <= 0x7e or 0xa0 <= cp <= 0xff) else 0x01000000 | cp
        else:
            return None
        kc = self.x.XKeysymToKeycode(self.d, sym)
        if kc:
            if named:
                return kc, None
            if self.x.XkbKeycodeToKeysym(self.d, kc, 0, 0) == sym:
                return kc, False
            if self.x.XkbKeycodeToKeysym(self.d, kc, 0, 1) == sym:
                return kc, True
        kc = self._spare_key(sym)
        return (kc, None) if kc else None

    def _spare_key(self, sym):
        """A character this keyboard layout has no key for: an unused key code is given it.  A few unused codes are kept, one per character,
        so typing two such characters in a row does not re-use a code before the program in front has read the first."""
        if self.spare is None:
            lo, hi = ctypes.c_int(), ctypes.c_int()
            self.x.XDisplayKeycodes(self.d, ctypes.byref(lo), ctypes.byref(hi))
            self.spare = [kc for kc in range(hi.value, lo.value, -1)
                          if not self.x.XkbKeycodeToKeysym(self.d, kc, 0, 0) and not self.x.XkbKeycodeToKeysym(self.d, kc, 0, 1)][:8]
            self.spare_sym, self.spare_next = {}, 0
        if not self.spare:
            return 0
        if sym in self.spare_sym:
            return self.spare_sym[sym]
        kc = self.spare[self.spare_next % len(self.spare)]
        self.spare_next += 1
        self.spare_sym = {s: k for s, k in self.spare_sym.items() if k != kc}
        self.spare_sym[sym] = kc
        syms = (ctypes.c_ulong * 1)(sym)
        self.x.XChangeKeyboardMapping(self.d, kc, 1, syms, 1)
        self.x.XSync(self.d, 0)
        time.sleep(0.05)                     # programs re-read the keyboard map when it changes; give them a moment
        return kc

    def raw_key(self, kc, down):
        self.t.XTestFakeKeyEvent(self.d, kc, 1 if down else 0, 0)

    def flush(self):
        self.x.XFlush(self.d)


class WinInput(_Keys):
    name = "Windows"

    def __init__(self):
        super().__init__()
        self.u = ctypes.windll.user32
        self.shift_code = 0x10

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_void_p)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.c_void_p)]

        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("u", _U)]
        self.INPUT, self.MOUSEINPUT, self.KEYBDINPUT = INPUT, MOUSEINPUT, KEYBDINPUT
        self.u.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
        self.u.VkKeyScanW.restype = ctypes.c_short

    def _mouse(self, flags, dx=0, dy=0, data=0):
        inp = self.INPUT(type=0)
        inp.u.mi = self.MOUSEINPUT(dx, dy, data & 0xffffffff, flags, 0, None)
        self.u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def move(self, x, y, w, h):
        self._mouse(0x8001, int(x * 65535 / max(w - 1, 1)), int(y * 65535 / max(h - 1, 1)))        # MOVE | ABSOLUTE

    def button(self, b, down):
        self._mouse({1: (0x2, 0x4), 2: (0x8, 0x10), 3: (0x20, 0x40)}.get(int(b), (0x2, 0x4))[0 if down else 1])

    def wheel(self, dy, dx=0):
        if dy:
            self._mouse(0x800, data=int(dy) * 120)
        if dx:
            self._mouse(0x1000, data=int(dx) * 120)

    def lookup(self, key):
        if key in WIN_VK:
            return ("vk", WIN_VK[key], key in WIN_EXTENDED), None
        if len(key) != 1:
            return None
        r = self.u.VkKeyScanW(ord(key))
        if r != -1 and not (r >> 8) & 0x6:                    # a plain key, with or without Shift
            return ("vk", r & 0xff, False), bool((r >> 8) & 1)
        return ("uni", ord(key), False), None

    def raw_key(self, code, down):
        if isinstance(code, int):
            code = ("vk", code, False)
        kind, val, ext = code
        flags = (0 if down else 0x2) | (0x1 if ext else 0)
        inp = self.INPUT(type=1)
        inp.u.ki = self.KEYBDINPUT(val, 0, flags, 0, None) if kind == "vk" else self.KEYBDINPUT(0, val, flags | 0x4, 0, None)
        self.u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def flush(self):
        pass


class UInput(_Keys):
    """Linux virtual keyboard and pointer through /dev/uinput: works under Wayland too.  Characters follow a US keyboard layout."""
    name = "uinput"
    EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
    BTN = {1: 0x110, 2: 0x111, 3: 0x112}

    def __init__(self):
        super().__init__()
        import fcntl
        self.shift_code = 42
        try:
            self.kb = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
            self.ms = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            raise BackendError("Keyboard and mouse are not allowed yet on that computer (" + (e.strerror or str(e)) + "). Run there once:  "
                               "python3 openpara_remote_helper.py --install   and restart it.")
        io = fcntl.ioctl
        set_ev, set_key, set_rel, set_abs = 0x40045564, 0x40045565, 0x40045566, 0x40045567

        def setup(fd, name):
            io(fd, 0x405c5503, struct.pack("HHHH80sI", 0x03, 0x1209, 0x0001, 1, name, 0))                 # UI_DEV_SETUP
            io(fd, 0x5501)                                                                               # UI_DEV_CREATE
        io(self.kb, set_ev, self.EV_KEY)
        for code in range(1, 249):
            io(self.kb, set_key, code)
        setup(self.kb, b"OpenPara Remote keyboard")
        for ev in (self.EV_KEY, self.EV_ABS, self.EV_REL):
            io(self.ms, set_ev, ev)
        for b in self.BTN.values():
            io(self.ms, set_key, b)
        for rel in (8, 6):                                                                               # REL_WHEEL, REL_HWHEEL
            io(self.ms, set_rel, rel)
        for axis in (0, 1):
            io(self.ms, set_abs, axis)
            io(self.ms, 0x401c5504, struct.pack("HHiiiiii", axis, 0, 0, 0, 65535, 0, 0, 0))               # UI_ABS_SETUP
        setup(self.ms, b"OpenPara Remote pointer")
        time.sleep(0.3)                                    # the desktop needs a moment to notice the new devices

    def _ev(self, fd, typ, code, val):
        os.write(fd, struct.pack("llHHi", 0, 0, typ, code, int(val)))

    def _syn(self, fd):
        self._ev(fd, self.EV_SYN, 0, 0)

    def move(self, x, y, w, h):
        self._ev(self.ms, self.EV_ABS, 0, x * 65535 / max(w - 1, 1))
        self._ev(self.ms, self.EV_ABS, 1, y * 65535 / max(h - 1, 1))
        self._syn(self.ms)

    def button(self, b, down):
        self._ev(self.ms, self.EV_KEY, self.BTN.get(int(b), 0x110), 1 if down else 0)
        self._syn(self.ms)

    def wheel(self, dy, dx=0):
        if dy:
            self._ev(self.ms, self.EV_REL, 8, dy)
        if dx:
            self._ev(self.ms, self.EV_REL, 6, dx)
        self._syn(self.ms)

    def lookup(self, key):
        if key in LINUX_KEYS:
            return LINUX_KEYS[key], None
        return LINUX_CHARS.get(key)

    def raw_key(self, code, down):
        self._ev(self.kb, self.EV_KEY, code, 1 if down else 0)
        self._syn(self.kb)

    def flush(self):
        pass


def make_input():
    if sys.platform == "win32":
        return WinInput()
    if sys.platform == "darwin":
        raise BackendError("Using the keyboard and mouse of a Mac is not supported yet.")
    return UInput() if is_wayland() else X11Input()


def apply_events(inp, events, w, h):
    for e in events:
        t = e.get("t")
        if t == "move":
            inp.move(float(e["x"]), float(e["y"]), w, h)
        elif t == "btn":
            inp.button(e.get("b", 1), bool(e.get("down")))
        elif t == "wheel":
            inp.wheel(int(e.get("dy", 0)), int(e.get("dx", 0)))
        elif t == "key":
            inp.key(e["key"], bool(e.get("down")))
        elif t == "text":
            inp.text(e.get("s", ""))
        elif t == "release":
            inp.release_all()
    inp.flush()


# ====================================================================================================== files

def list_drives():
    if os.name != "nt":
        return ["/"]
    bits = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{chr(65 + i)}:\\" for i in range(26) if bits >> i & 1]


def clean_path(path):
    p = os.path.expanduser(str(path or "~"))
    return os.path.abspath(p)


def list_dir(path):
    if os.name == "nt" and str(path) in ("", "/", "\\"):
        return {"path": "", "parent": None, "sep": os.sep, "entries": [[d, True, 0, 0] for d in list_drives()]}
    p = clean_path(path)
    entries = []
    with os.scandir(p) as it:
        for e in it:
            try:
                st = e.stat()
                entries.append([e.name, e.is_dir(), st.st_size, st.st_mtime])
            except OSError:
                entries.append([e.name, False, 0, 0])
    entries.sort(key=lambda r: (not r[1], r[0].lower()))
    parent = os.path.dirname(p)
    if parent == p:
        parent = "" if os.name == "nt" else None
    return {"path": p, "parent": parent, "sep": os.sep, "entries": entries}


def find_files(roots, name, depth):
    """Paths of files called `name` (any case) under the roots, at most `depth` folders down."""
    out, want = [], str(name).lower()
    for root in roots:
        root = clean_path(root)
        if not os.path.isdir(root):
            continue
        base = root.rstrip(os.sep).count(os.sep)
        for dp, dn, fn in os.walk(root):
            if dp.rstrip(os.sep).count(os.sep) - base >= depth:
                dn[:] = []
            dn[:] = [d for d in dn if not d.startswith(".")]
            out += [os.path.join(dp, f) for f in fn if f.lower() == want]
            if len(out) >= 200:
                return out
    return out


# ====================================================================================================== one connection

class Session(threading.Thread):
    def __init__(self, helper, sock, addr):
        super().__init__(daemon=True)
        self.helper, self.sock, self.addr = helper, sock, addr
        self.ch = None
        self.prev = None                       # (w, h, bpp, fmt, data) of the frame this client has
        self.soft = []                         # parts of the screen the client has only as JPEG (sent exact once they stand still)
        self.puts = {}                         # id -> {"f", "part", "path", "sha", "n", "mtime"}
        self.procs = {}                        # id -> Popen
        self.cancelled = set()
        self.input_error = None
        self.alive = True

    # ---- plumbing
    def reply(self, rid, payload=b"", **header):
        header["id"] = rid
        try:
            self.ch.send(header, payload)
        except (OSError, ConnectionError):
            self.alive = False

    def allowed(self, what):
        return bool(self.helper.cfg.get("allow_" + what, True))

    def run(self):
        ip = self.addr[0]
        try:
            self.sock.settimeout(20)
            self.ch, who = host_handshake(self.sock, self.helper.cfg, ip, self.helper.guard)
            self.sock.settimeout(None)
        except (RemoteError, ConnectionError, OSError, ValueError) as e:
            if str(e) == "wrong code":
                log(f"WRONG access code from {ip}")
            try:
                self.sock.close()
            except OSError:
                pass
            return
        if self.helper.cfg.get("ask") and not ask_on_screen(f"{who} ({ip}) wants to see and use this computer.\n\nAllow it?"):
            log(f"refused on this screen: {who} ({ip})")
            self.reply(0, op="welcome", error="The connection was refused on that computer's screen.")
            self.ch.close()
            return
        log(f"connected: {who} ({ip})")
        notify(f"{who} ({ip}) is connected to this computer.")
        self.helper.sessions.add(self)
        try:
            self.reply(0, op="welcome", ok=True)
            while self.alive:
                h, payload = self.ch.recv()
                self.dispatch(h, payload)
        except (ConnectionError, OSError, ValueError, struct.error):
            pass
        finally:
            self.cleanup()
            self.helper.sessions.discard(self)
            log(f"disconnected: {who} ({ip})")

    def cleanup(self):
        self.alive = False
        for p in list(self.procs.values()):
            kill_tree(p)
        for st in list(self.puts.values()):
            try:
                st["f"].close()
                os.remove(st["part"])
            except OSError:
                pass
        if self.helper.inp is not None:
            try:
                with self.helper.inp_lock:
                    self.helper.inp.release_all()
                    self.helper.inp.flush()
            except Exception:  # noqa: BLE001
                pass
        if self.ch:
            self.ch.close()

    def dispatch(self, h, payload):
        op, rid = h.get("op"), h.get("id")
        fn = getattr(self, "op_" + str(op), None)
        if fn is None:
            if rid is not None:
                self.reply(rid, error=f"This helper does not know '{op}' (it is older than your OpenPara).")
            return
        if op in self.THREADED:
            threading.Thread(target=self.guarded, args=(fn, h, payload), daemon=True).start()
        else:
            self.guarded(fn, h, payload)

    def guarded(self, fn, h, payload):
        try:
            fn(h, payload)
        except RemoteError as e:
            if h.get("id") is not None:
                self.reply(h["id"], error=str(e))
        except OSError as e:
            if h.get("id") is not None:
                self.reply(h["id"], error=(e.strerror or str(e)) + (f": {e.filename}" if e.filename else ""))
        except Exception as e:  # noqa: BLE001  (a bug here must not end the connection)
            if h.get("id") is not None:
                self.reply(h["id"], error=f"The helper hit a problem ({type(e).__name__}: {e}).")

    THREADED = {"frame", "ls", "get", "find", "hash", "exec", "delete"}

    def need(self, what, words):
        if not self.allowed(what):
            raise RemoteError(f"{words} is switched off on that computer (the helper was started with --no-{what}).")

    # ---- about
    def op_ping(self, h, payload):
        self.reply(h["id"], ok=True, t=time.time())

    def op_info(self, h, payload):
        hp = self.helper
        screen = {"ok": False, "why": "Showing the screen is switched off on that computer."}
        if self.allowed("screen"):
            try:
                w, hh, _bpp, _fmt, _d = hp.grab()
                screen = {"ok": True, "w": w, "h": hh, "backend": hp.screen.name}
            except RemoteError as e:
                screen = {"ok": False, "why": str(e)}
            except Exception as e:  # noqa: BLE001
                screen = {"ok": False, "why": f"The screen could not be read ({type(e).__name__}: {e})."}
        inp = {"ok": False, "why": "Keyboard and mouse are switched off on that computer."}
        if self.allowed("input"):
            try:
                inp = {"ok": True, "backend": hp.get_input().name}
            except RemoteError as e:
                inp = {"ok": False, "why": str(e)}
            except Exception as e:  # noqa: BLE001
                inp = {"ok": False, "why": f"Keyboard and mouse could not be set up ({type(e).__name__}: {e})."}
        self.reply(h["id"], name=hp.cfg.get("name") or socket.gethostname(), platform=sys.platform, system=platform.system(),
                   release=platform.release(), machine=platform.machine(), user=getpass.getuser(), home=os.path.expanduser("~"),
                   sep=os.sep, python=platform.python_version(), helper=HELPER_VERSION, screen=screen, input=inp,
                   jpeg=hp.jpeg is not None, files=self.allowed("files"), commands=self.allowed("commands"),
                   script=os.path.abspath(__file__), pid=os.getpid())

    def op_restart(self, h, payload):
        """Starts this helper again from its file (after OpenPara put a newer one in its place)."""
        self.need("commands", "Running commands")
        self.need("files", "Changing files")
        self.reply(h["id"], ok=True)
        threading.Timer(0.3, self.helper.restart).start()

    # ---- screen
    def op_frame(self, h, payload):
        self.need("screen", "Showing the screen")
        hp = self.helper
        wait = min(float(h.get("wait", 0)), 2.0)
        t_end = time.time() + wait
        while True:
            w, hh, bpp, fmt, data = hp.grab()
            prev = self.prev
            if h.get("full") or prev is None or prev[:4] != (w, hh, bpp, fmt):
                rects = [(0, 0, w, hh)]
                self.soft = []
            else:
                rects = diff_rects(data, prev[4], w, hh, bpp)
            if rects or self.soft or time.time() >= t_end or not self.alive:
                break
            time.sleep(0.05)
        self.prev = (w, hh, bpp, fmt, data)
        # JPEG only while a large part of the screen is moving (video); small changes (typing, menus) stay exact.  When the movement
        # stops, what was last sent as JPEG is sent once more, exact, so a picture that stands still is always sharp.
        area = sum(r[2] * r[3] for r in rects)
        lossy = bool(h.get("lossy")) and hp.jpeg is not None and area >= 0.15 * w * hh
        if not rects and self.soft:
            rects, self.soft = self.soft, []
        elif not lossy:
            self.soft = [r for r in self.soft if not any(covers(n, r) for n in rects)]
        q = max(20, min(95, int(h.get("quality", 70))))
        out, parts, soft = [], [], []
        for r in rects:
            raw = cut_rect(data, w, bpp, r)
            enc, blob = "z", None
            if lossy and r[2] * r[3] >= 4096:
                try:
                    enc, blob = "j", hp.jpeg(raw, r[2], r[3], fmt, q)
                    soft.append(r)
                except Exception:  # noqa: BLE001
                    enc = "z"
            if enc == "z":
                blob = zlib.compress(raw, 1)
            out.append([r[0], r[1], r[2], r[3], enc, len(blob)])
            parts.append(blob)
        if lossy:
            self.soft = soft
        self.reply(h["id"], b"".join(parts), w=w, h=hh, fmt=fmt, rects=out)

    def op_input(self, h, payload):
        if not self.allowed("input") or self.input_error:
            return
        hp = self.helper
        try:
            inp = hp.get_input()
            w, hh = hp.size
            with hp.inp_lock:
                apply_events(inp, h.get("ev", []), w, hh)
        except Exception as e:  # noqa: BLE001
            self.input_error = str(e) if isinstance(e, RemoteError) else f"Keyboard and mouse stopped working ({type(e).__name__}: {e})."
            self.reply(None, op="notice", text=self.input_error)

    # ---- files
    def op_ls(self, h, payload):
        self.need("files", "Looking at files")
        self.reply(h["id"], **list_dir(h.get("path", "")))

    def op_stat(self, h, payload):
        self.need("files", "Looking at files")
        p = clean_path(h["path"])
        if not os.path.exists(p):
            self.reply(h["id"], path=p, exists=False)
            return
        st = os.stat(p)
        self.reply(h["id"], path=p, exists=True, dir=os.path.isdir(p), size=st.st_size, mtime=st.st_mtime)

    def op_disk(self, h, payload):
        self.need("files", "Looking at files")
        u = shutil.disk_usage(clean_path(h.get("path", "~")))
        self.reply(h["id"], total=u.total, free=u.free)

    def op_find(self, h, payload):
        self.need("files", "Looking at files")
        self.reply(h["id"], paths=find_files(h.get("roots") or ["~"], h["name"], min(int(h.get("depth", 4)), 8)))

    def op_hash(self, h, payload):
        self.need("files", "Looking at files")
        sha = hashlib.sha256()
        with open(clean_path(h["path"]), "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                sha.update(block)
        self.reply(h["id"], sha256=sha.hexdigest())

    def op_mkdir(self, h, payload):
        self.need("files", "Changing files")
        os.makedirs(clean_path(h["path"]), exist_ok=True)
        self.reply(h["id"], ok=True)

    def op_rename(self, h, payload):
        self.need("files", "Changing files")
        src, dst = clean_path(h["src"]), clean_path(h["dst"])
        if os.path.exists(dst) and not h.get("replace"):
            raise RemoteError(f"{os.path.basename(dst)} is already there.")
        os.replace(src, dst)
        self.reply(h["id"], ok=True)

    def op_delete(self, h, payload):
        self.need("files", "Changing files")
        p = clean_path(h["path"])
        if os.path.isdir(p) and not os.path.islink(p):
            if h.get("recursive"):
                shutil.rmtree(p)
            else:
                os.rmdir(p)
        else:
            os.remove(p)
        self.reply(h["id"], ok=True)

    def op_get(self, h, payload):
        self.need("files", "Copying files")
        rid, p = h["id"], clean_path(h["path"])
        st = os.stat(p)
        with open(p, "rb") as f:
            f.seek(int(h.get("offset", 0)))
            self.reply(rid, size=st.st_size, mtime=st.st_mtime, start=True)
            while self.alive and rid not in self.cancelled:
                block = f.read(CHUNK)
                if not block:
                    break
                self.reply(rid, block, data=True)
        self.reply(rid, eof=True, cancelled=rid in self.cancelled)
        self.cancelled.discard(rid)

    def op_put(self, h, payload):
        self.need("files", "Copying files")
        p = clean_path(h["path"])
        if h.get("mkdirs", True):
            os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.isdir(p):
            raise RemoteError(f"{os.path.basename(p)} is a folder there.")
        part = p + ".part"
        self.puts[h["id"]] = {"f": open(part, "wb"), "part": part, "path": p, "sha": hashlib.sha256(), "n": 0, "mtime": h.get("mtime")}
        self.reply(h["id"], ready=True)

    def op_put_data(self, h, payload):
        st = self.puts.get(h["id"])
        if st is None:
            return
        try:
            if payload:
                st["f"].write(payload)
                st["sha"].update(payload)
                st["n"] += len(payload)
            if h.get("abort"):
                raise RemoteError("stopped")
            if h.get("eof"):
                st["f"].flush()
                os.fsync(st["f"].fileno())
                st["f"].close()
                os.replace(st["part"], st["path"])
                if st["mtime"]:
                    try:
                        os.utime(st["path"], (st["mtime"], st["mtime"]))
                    except OSError:
                        pass
                del self.puts[h["id"]]
                self.reply(h["id"], done=True, size=st["n"], sha256=st["sha"].hexdigest())
        except (OSError, RemoteError) as e:
            self.puts.pop(h["id"], None)
            try:
                st["f"].close()
                os.remove(st["part"])
            except OSError:
                pass
            if not h.get("abort"):
                self.reply(h["id"], error=(getattr(e, "strerror", None) or str(e)))

    def op_cancel(self, h, payload):
        rid = h.get("target")
        self.cancelled.add(rid)
        p = self.procs.get(rid)
        if p is not None:
            kill_tree(p)

    # ---- commands
    def op_exec(self, h, payload):
        self.need("commands", "Running commands")
        rid, cmd = h["id"], h["cmd"]
        cwd = clean_path(h["cwd"]) if h.get("cwd") else os.path.expanduser("~")
        kw = dict(cwd=cwd, shell=isinstance(cmd, str))
        if os.name == "nt":
            kw["creationflags"] = 0x00000200 | 0x08000000                     # new process group, no console window
        else:
            kw["start_new_session"] = True
        if h.get("detach"):                                                    # a program that keeps running on that screen
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
            self.reply(rid, done=True, pid=p.pid, code=None)
            return
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
        self.procs[rid] = p
        if rid in self.cancelled:                                              # stopped before it had really started
            kill_tree(p)
        timeout = float(h.get("timeout") or 0)
        if timeout:
            threading.Timer(timeout, lambda: p.poll() is None and (self.cancelled.add(rid), kill_tree(p))).start()
        enc = "utf-8"
        try:
            while True:
                block = p.stdout.read1(65536) if hasattr(p.stdout, "read1") else p.stdout.read(4096)
                if not block:
                    break
                try:
                    text = block.decode(enc)
                except UnicodeDecodeError:
                    text = block.decode("oem" if os.name == "nt" else enc, "replace")
                self.reply(rid, out=text)
            code = p.wait()
        finally:
            self.procs.pop(rid, None)
        self.reply(rid, done=True, code=code, stopped=rid in self.cancelled)
        self.cancelled.discard(rid)

    def op_exec_in(self, h, payload):
        p = self.procs.get(h.get("target"))
        if p is not None and p.stdin:
            try:
                p.stdin.write(str(h.get("data", "")).encode("utf-8"))
                p.stdin.flush()
                if h.get("close"):
                    p.stdin.close()
            except OSError:
                pass


def kill_tree(p):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        else:
            import signal
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        p.kill()
    except OSError:
        pass


def ask_on_screen(text):
    """Allow / Deny on this computer's own screen (a small window of its own, so it works from any thread).  No way to ask = no."""
    code = ("import sys,tkinter as tk\nfrom tkinter import messagebox\nr=tk.Tk();r.withdraw();r.attributes('-topmost',True)\n"
            "sys.exit(0 if messagebox.askyesno('OpenPara Remote helper',sys.argv[1],parent=r) else 1)\n")
    try:
        return subprocess.run([sys.executable, "-c", code, text], timeout=45).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def notify(text):
    if os.name != "nt" and shutil.which("notify-send"):
        try:
            subprocess.Popen(["notify-send", "-t", "6000", "OpenPara Remote helper", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


# ====================================================================================================== the helper itself

class Helper:
    def __init__(self, cfg, port=None, bind="0.0.0.0", discovery=True):
        self.cfg = cfg
        self.port = int(port if port is not None else cfg.get("port", PORT))
        self.bind = bind
        self.discovery = discovery
        self.guard = Guard()
        self.sessions = set()
        self.screen = None
        self.screen_lock = threading.Lock()
        self.inp = None
        self.inp_lock = threading.Lock()
        self.size = (1, 1)
        self.jpeg = jpeg_encoder()
        self.listeners = {}                  # network port (number, name), or None for "all" -> (TCP listener, UDP socket or None)
        self.per_port = False
        self.running = False

    def grab(self):
        with self.screen_lock:
            if self.screen is None:
                self.screen = make_screen()
            f = self.screen.grab()
            self.size = (f[0], f[1])
            return f

    def get_input(self):
        with self.inp_lock:
            if self.inp is None:
                self.inp = make_input()
            return self.inp

    # ---- listening.  On Linux there is one listener per network port (Wi-Fi, wired ...), each tied to its port, so that an answer leaves
    # through the port the question came in by.  Without that, a computer with two ports in the same address range (a Raspberry Pi on a
    # 192.168.1.x Wi-Fi whose wired port has 192.168.1.2 for an instrument) answers through the wrong one and nobody can connect.
    def _tcp(self, dev=None):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name != "nt":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if dev:
                s.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, dev.encode("utf-8") + b"\0")
            s.bind(("0.0.0.0" if dev else self.bind, self.port))
            s.listen(8)
            s.settimeout(1.0)
        except OSError:
            s.close()
            raise
        self.port = s.getsockname()[1]
        return s

    def _udp(self, dev=None):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if dev:
                s.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, dev.encode("utf-8") + b"\0")
            s.bind(("0.0.0.0", int(self.cfg.get("discovery_port", DISCOVERY_PORT))))
            s.settimeout(1.0)
        except OSError:
            s.close()
            raise
        return s

    def _open(self, key=None):
        """Starts listening on one network port (key = (number, name)), or on all of them at once (None)."""
        dev = key[1] if key else None
        srv = self._tcp(dev)
        udp = None
        if self.discovery:
            try:
                udp = self._udp(dev)
            except OSError:
                udp = None                       # another helper answers searches already; connecting by address still works
        self.listeners[key] = (srv, udp)
        threading.Thread(target=self.accept_loop, args=(srv,), daemon=True).start()
        if udp is not None:
            threading.Thread(target=self.discovery_loop, args=(udp,), daemon=True).start()

    def _close(self, key):
        for s in self.listeners.pop(key, ()):
            if s is None:
                continue
            try:
                s.shutdown(socket.SHUT_RDWR)         # wakes a thread that waits on it (Linux); elsewhere its one-second wait ends it
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

    def start(self):
        self.listeners = {}
        self.running = True
        self.per_port = False
        ports = interfaces() if self.bind == "0.0.0.0" else []
        for key in ports:
            try:
                self._open(key)
            except PermissionError:                  # an old system that does not let a normal program do this: one listener for all
                for k in list(self.listeners):
                    self._close(k)
                break
            except OSError as e:
                if e.errno == errno.EADDRINUSE:      # the port number is taken (the helper is running already): said by the caller
                    for k in list(self.listeners):
                        self._close(k)
                    raise
                continue                             # this one network port cannot be listened on (it just went away): the others can
        self.per_port = bool(self.listeners)
        if self.per_port:
            threading.Thread(target=self.watch_ports, daemon=True).start()
        else:
            self._open(None)
        return self

    def watch_ports(self):
        """A network port that appears later (a USB Wi-Fi stick, a phone's tethering) gets its listener; one that is gone loses it."""
        while self.running:
            time.sleep(5.0)
            if not self.running:
                break
            now = set(interfaces())
            for key in [k for k in self.listeners if k not in now]:
                self._close(key)
            for key in now:
                if key not in self.listeners and self.running:
                    try:
                        self._open(key)
                    except OSError:
                        pass

    def accept_loop(self, srv):
        while self.running:
            try:
                sock, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.running:
                sock.close()
                break
            if len(self.sessions) >= 8 or threading.active_count() > 96:      # also: not an endless pile of half-open connections
                sock.close()
                continue
            try:
                sock.settimeout(None)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            Session(self, sock, addr).start()

    def discovery_loop(self, udp):
        while self.running:
            try:
                data, addr = udp.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            if data.strip() == DISCOVER:
                ans = {"oprh": PROTO, "name": self.cfg.get("name") or socket.gethostname(), "platform": sys.platform, "port": self.port,
                       "helper": HELPER_VERSION}
                try:
                    udp.sendto(json.dumps(ans).encode("utf-8"), addr)
                except OSError:
                    pass

    def restart(self):
        """Ends this helper and starts the one in its file a moment later, on its own (so it survives this one ending)."""
        code = "import subprocess, sys, time; time.sleep(1.5); subprocess.Popen([sys.executable, sys.argv[1]])"
        kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
        try:
            subprocess.Popen([sys.executable or "python3", "-c", code, os.path.abspath(__file__)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        except OSError as e:
            log(f"could not start again after an update ({e}); still running the old helper")
            return
        log("starting again (the helper file was updated)")
        self.stop()
        os._exit(0)

    def stop(self):
        self.running = False
        for key in list(self.listeners):
            self._close(key)
        for sess in list(self.sessions):
            sess.cleanup()


# ====================================================================================================== install / command line

def install_dir():
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "OpenParaRemote")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "openpara-remote")


def autostart_file():
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
                            "OpenPara Remote helper.bat")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "autostart",
                        "openpara-remote-helper.desktop")


UINPUT_RULE = "/etc/udev/rules.d/60-openpara-remote-uinput.rules"


def install(extra_args=""):
    """Copies this file to the computer itself (so it works without the USB drive) and starts it with every login."""
    d = install_dir()
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, "openpara_remote_helper.py")
    if os.path.abspath(__file__) != os.path.abspath(dest):
        shutil.copyfile(os.path.abspath(__file__), dest)
    auto = autostart_file()
    os.makedirs(os.path.dirname(auto), exist_ok=True)
    if os.name == "nt":
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        exe = pyw if os.path.exists(pyw) else sys.executable
        with open(auto, "w", encoding="utf-8") as f:
            f.write(f'@echo off\r\nstart "" "{exe}" "{dest}" {extra_args}\r\n')
        subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule", "name=OpenPara Remote helper", "dir=in", "action=allow",
                        f"program={exe}", "profile=private", "enable=yes"], capture_output=True)
        print("Windows may ask once whether Python may be reached on private networks: answer Allow (it needs to be seen on the screen).")
    else:
        with open(auto, "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\nType=Application\nName=OpenPara Remote helper\nComment=Lets OpenPara see and use this computer (with the "
                    f"access code)\nExec={sys.executable or 'python3'} {dest} {extra_args}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")
        if is_wayland() or os.path.exists("/dev/uinput"):
            print("Allowing the helper to use the keyboard and mouse (this asks for the administrator password if one is needed) ...")
            rule = 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"'
            sh = (f"echo '{rule}' > {UINPUT_RULE} && usermod -aG input {getpass.getuser()} && udevadm control --reload-rules && "
                  "udevadm trigger /dev/uinput; modprobe uinput; true")
            try:
                r = subprocess.run(["sudo", "sh", "-c", sh])
                print("Done - restart this computer once so that it takes effect." if r.returncode == 0 else
                      "That did not work; keyboard and mouse may stay unavailable on a Wayland desktop.")
            except OSError:
                print("sudo is not available; keyboard and mouse may stay unavailable on a Wayland desktop.")
    print(f"Installed: {dest}\nStarts with every login: {auto}")
    return dest


def start_detached(dest, port):
    """Starts the installed helper now, on its own, so the computer does not have to be restarted first.  Returns what to tell the person."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(1)
    try:
        probe.connect(("127.0.0.1", port))
        return "A helper is already running here; the new settings are used from the next login (or restart this computer now)."
    except OSError:
        pass
    finally:
        probe.close()
    kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}          # detached
    exe = sys.executable or "python3"
    if os.name == "nt" and os.path.exists(os.path.join(os.path.dirname(exe), "pythonw.exe")):
        exe = os.path.join(os.path.dirname(exe), "pythonw.exe")
    try:
        subprocess.Popen([exe, dest], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    except OSError as e:
        return f"It could not be started right now ({e}); it starts with the next login."
    return "The helper is running now, and starts by itself after every login."


def uninstall():
    for p in (autostart_file(), os.path.join(install_dir(), "openpara_remote_helper.py")):
        try:
            os.remove(p)
            print("Removed", p)
        except OSError:
            pass
    if os.name != "nt" and os.path.exists(UINPUT_RULE):
        subprocess.run(["sudo", "rm", "-f", UINPUT_RULE])
    print("The helper no longer starts by itself. Its settings folder is left in place:", config_dir())


def check():
    """Says what works on this computer: the screen, keyboard and mouse, JPEG.  Nothing is changed (the pointer is moved to where it is)."""
    print(f"OpenPara Remote helper {HELPER_VERSION} on {platform.system()} {platform.release()} ({platform.machine()}), Python {platform.python_version()}")
    if sys.platform.startswith("linux"):
        print("Desktop:", "Wayland" if is_wayland() else "X11" if os.environ.get("DISPLAY") else "none found (start this from the desktop session)")
    size = None
    try:
        scr = make_screen()
        w, h, bpp, fmt, data = scr.grab()
        size = (w, h)
        dark = not any(data[i] for i in range(0, len(data), max(1, len(data) // 5000)))
        print(f"Screen: ok - {w} x {h} through {scr.name}" + ("  (the picture is all black: is the screen off or locked?)" if dark else ""))
    except Exception as e:  # noqa: BLE001
        print(f"Screen: NOT available - {e if isinstance(e, RemoteError) else type(e).__name__ + ': ' + str(e)}")
    try:
        inp = make_input()
        inp.key("Shift", True)
        inp.key("Shift", False)
        inp.flush()
        print(f"Keyboard and mouse: ok - through {inp.name}")
    except Exception as e:  # noqa: BLE001
        print(f"Keyboard and mouse: NOT available - {e if isinstance(e, RemoteError) else type(e).__name__ + ': ' + str(e)}")
    print("Moving pictures: " + ("JPEG (light)" if jpeg_encoder() else "exact only - installing OpenCV or Pillow here makes video much lighter"))
    print("Addresses:", describe_addresses() or "none (not on a network?)", " - type the first one into OpenPara")
    return size


def show_code(code):
    print("\n    Access code:   " + code + "\n")
    print("Type it into OpenPara (Remote Computer) when it asks. It is not shown again: write it down, or run --new-code for a new one.\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lets OpenPara see and use this computer over the local network, with an access code.")
    ap.add_argument("--install", action="store_true", help="copy the helper to this computer and start it with every login")
    ap.add_argument("--uninstall", action="store_true", help="stop starting it with every login")
    ap.add_argument("--new-code", action="store_true", help="make a new access code and show it")
    ap.add_argument("--code", help="use this access code (at least 8 letters or digits) instead of a made-up one")
    ap.add_argument("--pbkdf2", action="store_true", help="store the code in the way every Python can check (use if OpenPara asks for it)")
    ap.add_argument("--name", help="the name OpenPara shows for this computer")
    ap.add_argument("--port", type=int, help=f"the port to listen on (normally {PORT})")
    ap.add_argument("--ask", action="store_true", help="ask on this screen before every connection")
    ap.add_argument("--no-ask", action="store_true", help="do not ask on this screen (a computer nobody sits at)")
    for part, words in (("screen", "showing the screen"), ("input", "keyboard and mouse"), ("files", "copying files"), ("commands", "running commands")):
        ap.add_argument(f"--no-{part}", action="store_true", help=f"switch off {words}")
        ap.add_argument(f"--{part}", action="store_true", help=f"switch {words} back on")
    ap.add_argument("--status", action="store_true", help="show the settings and stop")
    ap.add_argument("--check", action="store_true", help="say what works on this computer (screen, keyboard and mouse) and stop")
    a = ap.parse_args(argv)

    if sys.stdout is None:                                   # pythonw: nothing to print to
        sys.stdout = sys.stderr = open(os.devnull, "w")
    if a.uninstall:
        uninstall()
        return 0
    if a.check:
        check()
        return 0
    cfg = load_config()
    changed = False
    for key, val in (("name", a.name), ("port", a.port)):
        if val:
            cfg[key], changed = val, True
    if a.ask or a.no_ask:
        cfg["ask"], changed = bool(a.ask), True
    for part in ("screen", "input", "files", "commands"):
        if getattr(a, "no_" + part):
            cfg["allow_" + part], changed = False, True
        elif getattr(a, part):
            cfg["allow_" + part], changed = True, True
    code = None
    if a.code or a.new_code or not cfg.get("w"):
        if not (a.code or a.new_code) and not sys.stdin.isatty() and not a.install:
            log("No access code is set. Start the helper once in a terminal to make one.")
            return 2
        code = a.code or new_code()
        try:
            set_code(cfg, code, {"name": "pbkdf2", "iter": 300000} if a.pbkdf2 else None)
        except RemoteError as e:
            print(e)
            return 2
        changed = True
    if changed:
        save_config(cfg)
    if code:
        show_code(code)
    if a.status:
        print("Settings folder:", config_dir())
        print("Name:", cfg.get("name") or socket.gethostname(), " Port:", cfg.get("port", PORT), " Ask on screen:", bool(cfg.get("ask")))
        print("Allowed:", ", ".join(p for p in ("screen", "input", "files", "commands") if cfg.get("allow_" + p, True)) or "nothing")
        return 0
    if a.install:
        dest = install()
        print(start_detached(dest, int(cfg.get("port", PORT))))
        return 0
    try:
        hp = Helper(cfg).start()
    except OSError as e:
        log(f"Could not start: port {cfg.get('port', PORT)} is in use (is the helper already running?)  [{e}]")
        return 1
    ips = describe_addresses() or "unknown"
    log(f"OpenPara Remote helper {HELPER_VERSION} is running on {socket.gethostname()}  -  address {ips}, port {hp.port}.  Ctrl+C stops it.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    hp.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
