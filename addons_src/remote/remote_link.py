"""remote_link.py - OpenPara's side of a connection to a computer that runs openpara_remote_helper.py.  No Qt here, so it is testable.

    link = Link("192.168.1.42", code="ABCD-EFGH-JKMN").connect()
    link.info                      what that computer is and what it allows
    link.frame(...)                the changed parts of its screen          link.input([...])    keyboard / mouse events
    link.ls(path) / download / upload / download_tree / upload_tree / mkdir / rename / delete / find / file_hash
    link.run("ls -l")              (exit code, text)                        link.spawn(...)      a command whose output arrives as it runs
    discover()                     the helpers that answer on this network

Every call that waits raises RemoteError with words for the person when that computer says no, and LinkClosed when the connection is gone.
The saved list of computers (name, address, and the code only when asked to remember it) is in <user folder>/remote_computers.json.
"""
import hashlib
import json
import os
import queue
import socket
import threading
import time

import openpara_remote_helper as H

RemoteError = H.RemoteError
PORT = H.PORT


class LinkClosed(RemoteError):
    pass


class Stopped(RemoteError):
    """The person stopped a copy."""


class Link:
    def __init__(self, host, port=PORT, code="", name=None, timeout=8.0):
        self.host, self.port, self.code = str(host).strip(), int(port or PORT), code
        self.name = name or socket.gethostname()
        self.timeout = timeout
        self.ch = None
        self.info = {}
        self.hello = {}
        self.closed = True
        self.why_closed = ""
        self.on_notice = None                 # fn(text): something that computer wants the person to know
        self.on_closed = None                 # fn(why)
        self._id = 0
        self._lock = threading.Lock()
        self._waiting = {}                    # id -> queue of (header, payload)

    # ---------------------------------------------------------------- connection
    def connect(self):
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except socket.gaierror:
            raise RemoteError(f"No computer called '{self.host}' was found. Check the name, or use its address (numbers like 192.168.1.42).")
        except (ConnectionRefusedError, TimeoutError, socket.timeout, OSError) as e:
            raise RemoteError(f"{self.host} does not answer on port {self.port}. Is the helper running there, and are both computers on the "
                              f"same network?  ({getattr(e, 'strerror', None) or e})")
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(60)                 # the other side may be asking its person to allow this
            self.ch, self.hello = H.client_handshake(sock, self.code, self.name)
            h, _ = self.ch.recv()
            if h.get("error"):
                raise RemoteError(str(h["error"]))
            sock.settimeout(None)
        except (ConnectionError, socket.timeout, TimeoutError, OSError, ValueError) as e:
            sock.close()
            raise RemoteError(f"{self.host} answered, but the connection did not get through ({e}).")
        except RemoteError:
            sock.close()
            raise
        self.closed = False
        threading.Thread(target=self._reader, daemon=True).start()
        self.info = self.request("info", timeout=40)[0]
        return self

    def _reader(self):
        why = "The connection was closed."
        try:
            while True:
                h, payload = self.ch.recv()
                rid = h.get("id")
                q = self._waiting.get(rid)
                if q is not None:
                    q.put((h, payload))
                elif h.get("op") == "notice" and self.on_notice:
                    try:
                        self.on_notice(str(h.get("text", "")))
                    except Exception:  # noqa: BLE001
                        pass
        except (ConnectionError, OSError, ValueError) as e:
            if not self.closed:
                why = f"The connection to {self.label()} was lost ({e})."
        was_open = not self.closed
        self.closed, self.why_closed = True, why
        for q in list(self._waiting.values()):
            q.put((None, None))
        if was_open and self.on_closed:
            try:
                self.on_closed(why)
            except Exception:  # noqa: BLE001
                pass

    def label(self):
        return self.info.get("name") or self.hello.get("name") or self.host

    def close(self):
        if self.ch is not None and not self.closed:
            self.closed, self.why_closed = True, "Disconnected."
            self.ch.close()

    # ---------------------------------------------------------------- messages
    def _new_id(self):
        with self._lock:
            self._id += 1
            return self._id

    def send(self, header, payload=b""):
        if self.closed:
            raise LinkClosed(self.why_closed or "Not connected.")
        try:
            self.ch.send(header, payload)
        except (OSError, ConnectionError) as e:
            raise LinkClosed(f"The connection to {self.label()} was lost ({e}).")

    def open_stream(self, op, payload=b"", **kw):
        """Sends a request and returns (id, queue of its answers); the caller reads with next_msg and ends with end_stream."""
        rid = self._new_id()
        q = queue.Queue()
        self._waiting[rid] = q
        try:
            self.send(dict(kw, op=op, id=rid), payload)
        except RemoteError:
            self._waiting.pop(rid, None)
            raise
        return rid, q

    def next_msg(self, q, timeout=60):
        try:
            h, payload = q.get(timeout=timeout)
        except queue.Empty:
            raise RemoteError(f"{self.label()} did not answer in time.")
        if h is None:
            raise LinkClosed(self.why_closed or "The connection was closed.")
        if h.get("error"):
            raise RemoteError(str(h["error"]))
        return h, payload

    def end_stream(self, rid):
        self._waiting.pop(rid, None)

    def request(self, op, payload=b"", timeout=30, **kw):
        rid, q = self.open_stream(op, payload, **kw)
        try:
            return self.next_msg(q, timeout)
        finally:
            self.end_stream(rid)

    # ---------------------------------------------------------------- screen, keyboard and mouse
    def frame(self, full=False, lossy=True, quality=70, wait=0.5):
        """(header, bytes): header has w, h, fmt and rects [[x, y, w, h, 'z' | 'j', bytes]...]; the bytes are the rects one after another."""
        return self.request("frame", full=bool(full), lossy=bool(lossy), quality=int(quality), wait=wait, timeout=40)

    def input(self, events):
        if events:
            self.send({"op": "input", "ev": list(events)})

    # ---------------------------------------------------------------- files
    def ls(self, path=""):
        return self.request("ls", path=path)[0]

    def stat(self, path):
        return self.request("stat", path=path)[0]

    def disk(self, path="~"):
        return self.request("disk", path=path)[0]

    def find(self, name, roots, depth=4):
        return self.request("find", name=name, roots=list(roots), depth=depth, timeout=90)[0]["paths"]

    def file_hash(self, path):
        return self.request("hash", path=path, timeout=600)[0]["sha256"]

    def mkdir(self, path):
        self.request("mkdir", path=path)

    def rename(self, src, dst, replace=False):
        self.request("rename", src=src, dst=dst, replace=replace)

    def delete(self, path, recursive=False):
        self.request("delete", path=path, recursive=recursive, timeout=300)

    def join(self, *parts):
        """A path on that computer, joined with its own separator."""
        sep = self.info.get("sep") or "/"
        out = str(parts[0])
        for p in parts[1:]:
            out = out.rstrip("/\\") + sep + str(p).strip("/\\") if out else str(p)
        return out

    def read_file(self, path, limit=8 * 1024 * 1024):
        """The bytes of a small file there."""
        rid, q = self.open_stream("get", path=path)
        out = bytearray()
        try:
            while True:
                h, payload = self.next_msg(q)
                if h.get("eof"):
                    return bytes(out)
                out += payload
                if len(out) > limit:
                    self.send({"op": "cancel", "target": rid})
                    raise RemoteError(f"{os.path.basename(path)} is larger than expected.")
        finally:
            self.end_stream(rid)

    def write_file(self, path, data):
        """Small data as a file there (written whole, then renamed into place)."""
        rid, q = self.open_stream("put", path=path, size=len(data))
        try:
            self.next_msg(q)
            self.send({"op": "put_data", "id": rid, "eof": True}, data)
            return self.next_msg(q, timeout=120)[0]
        finally:
            self.end_stream(rid)

    def download(self, remote, local, progress=None, stop=None):
        """Copies a file from there to `local` (a .part file first).  progress(done, total); stop() -> True ends it with Stopped."""
        rid, q = self.open_stream("get", path=remote)
        part = local + ".part"
        os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
        done = total = 0
        mtime, stopped = None, False
        try:
            with open(part, "wb") as f:
                while True:
                    h, payload = self.next_msg(q, timeout=120)
                    if h.get("start"):
                        total, mtime = int(h.get("size", 0)), h.get("mtime")
                    elif h.get("eof"):
                        if h.get("cancelled") or stopped:
                            raise Stopped("Stopped.")
                        break
                    else:
                        f.write(payload)
                        done += len(payload)
                        if progress:
                            progress(done, total)
                        if stop and stop():
                            self.send({"op": "cancel", "target": rid})
                            stop, stopped = None, True
            os.replace(part, local)
            if mtime:
                try:
                    os.utime(local, (mtime, mtime))
                except OSError:
                    pass
            return done
        except BaseException:
            try:
                os.remove(part)
            except OSError:
                pass
            raise
        finally:
            self.end_stream(rid)

    def upload(self, local, remote, progress=None, stop=None):
        """Copies a file to there; what arrived is compared with what was sent (SHA-256).  Returns the size."""
        size = os.path.getsize(local)
        rid, q = self.open_stream("put", path=remote, size=size, mtime=os.path.getmtime(local))
        sha = hashlib.sha256()
        done = 0
        try:
            self.next_msg(q)
            with open(local, "rb") as f:
                while True:
                    block = f.read(H.CHUNK)
                    last = len(block) < H.CHUNK
                    if stop and stop():
                        self.send({"op": "put_data", "id": rid, "abort": True})
                        raise Stopped("Stopped.")
                    sha.update(block)
                    self.send({"op": "put_data", "id": rid, "eof": last}, block)
                    done += len(block)
                    if progress:
                        progress(done, size)
                    if last:
                        break
            h, _ = self.next_msg(q, timeout=300)
            if h.get("sha256") != sha.hexdigest():
                raise RemoteError(f"{os.path.basename(local)} did not arrive whole. Send it again.")
            return done
        finally:
            self.end_stream(rid)

    def walk(self, remote_dir):
        """[(relative path with '/', size, mtime)] of every file under a folder there."""
        out, todo = [], [("", remote_dir)]
        while todo:
            rel, path = todo.pop()
            for name, is_dir, size, mtime in self.ls(path)["entries"]:
                r = f"{rel}/{name}" if rel else name
                if is_dir:
                    todo.append((r, self.join(path, name)))
                else:
                    out.append((r, size, mtime))
        return sorted(out)

    def download_tree(self, remote_dir, local_dir, progress=None, stop=None):
        """Copies a folder from there.  A file that is already here with the same size is left alone, so a copy that was cut off can be
        continued.  progress(bytes done, bytes total, file name).  Returns (files copied, files already here)."""
        files = self.walk(remote_dir)
        total = sum(f[1] for f in files)
        base = copied = skipped = 0
        for rel, size, _mt in files:
            local = os.path.join(local_dir, *rel.split("/"))
            if os.path.isfile(local) and os.path.getsize(local) == size:
                skipped += 1
            else:
                self.download(self.join(remote_dir, *rel.split("/")), local,
                              (lambda d, _t, b=base, r=rel: progress(b + d, total, r)) if progress else None, stop)
                copied += 1
            base += size
            if progress:
                progress(base, total, rel)
        return copied, skipped

    def upload_tree(self, local_dir, remote_dir, progress=None, stop=None):
        files = []
        for dp, _dn, fn in os.walk(local_dir):
            for f in fn:
                p = os.path.join(dp, f)
                files.append((os.path.relpath(p, local_dir).replace(os.sep, "/"), p, os.path.getsize(p)))
        total = sum(f[2] for f in files)
        base = 0
        self.mkdir(remote_dir)
        for rel, p, size in sorted(files):
            self.upload(p, self.join(remote_dir, *rel.split("/")), (lambda d, _t, b=base, r=rel: progress(b + d, total, r)) if progress else None, stop)
            base += size
        return len(files)

    # ---------------------------------------------------------------- commands
    def spawn(self, cmd, cwd=None, on_out=None, on_done=None, timeout=0):
        """Starts a command there; on_out(text) as it prints, on_done(exit code or None, stopped).  Returns its id (for kill / write_in)."""
        rid, q = self.open_stream("exec", cmd=cmd, cwd=cwd, timeout=timeout)

        def pump():
            code, stopped = None, False
            try:
                while True:
                    h, _ = self.next_msg(q, timeout=None)
                    if h.get("out") and on_out:
                        on_out(h["out"])
                    if h.get("done"):
                        code, stopped = h.get("code"), bool(h.get("stopped"))
                        break
            except RemoteError as e:
                if on_out:
                    on_out(f"\n{e}\n")
            finally:
                self.end_stream(rid)
                if on_done:
                    on_done(code, stopped)
        threading.Thread(target=pump, daemon=True).start()
        return rid

    def kill(self, rid):
        self.send({"op": "cancel", "target": rid})

    def write_in(self, rid, text):
        self.send({"op": "exec_in", "target": rid, "data": text})

    def run(self, cmd, cwd=None, timeout=60):
        """Runs a command there and waits: (exit code, everything it printed)."""
        rid, q = self.open_stream("exec", cmd=cmd, cwd=cwd, timeout=timeout)
        out = []
        try:
            while True:
                h, _ = self.next_msg(q, timeout=timeout + 15)
                if h.get("out"):
                    out.append(h["out"])
                if h.get("done"):
                    return h.get("code"), "".join(out)
        finally:
            self.end_stream(rid)

    def launch(self, cmd, cwd=None):
        """Starts a program there that keeps running on its own (on that computer's screen); returns its process number."""
        return self.request("exec", cmd=cmd, cwd=cwd, detach=True)[0].get("pid")


# ---------------------------------------------------------------- finding helpers on the network

def discover(timeout=1.5, port=H.DISCOVERY_PORT, extra=()):
    """[{'host', 'port', 'name', 'platform', 'helper'}] of the helpers that answer a search on this network (and at the `extra` addresses)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.25)
    targets = {"255.255.255.255"} | set(extra)
    for ip in H.local_addresses():
        targets.add(ip.rsplit(".", 1)[0] + ".255")
    found = {}
    try:
        for t in targets:
            try:
                s.sendto(H.DISCOVER, (t, port))
            except OSError:
                pass
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                a = json.loads(data.decode("utf-8"))
                if a.get("oprh"):
                    found[(addr[0], int(a["port"]))] = {"host": addr[0], "port": int(a["port"]), "name": str(a.get("name", addr[0]))[:60],
                                                        "platform": str(a.get("platform", "")), "helper": str(a.get("helper", ""))}
            except (ValueError, KeyError, TypeError):
                pass
    finally:
        s.close()
    one = {}                                  # a helper that answered on two addresses (two network cards, or this PC itself) is listed once
    for d in found.values():
        key = (d["name"], d["port"])
        if key not in one or one[key]["host"].startswith("127."):
            one[key] = d
    return sorted(one.values(), key=lambda d: d["name"].lower())


# ---------------------------------------------------------------- the saved computers

def _store():
    try:
        import paths
        base = paths.user_dir()
    except ImportError:
        base = os.path.join(os.path.expanduser("~"), ".openpara")
    return os.path.join(base, "remote_computers.json")


def load_computers():
    try:
        with open(_store(), encoding="utf-8") as f:
            data = json.load(f)
        return [c for c in data if isinstance(c, dict) and c.get("host")]
    except (OSError, ValueError, TypeError):
        return []


def save_computers(items):
    path = _store()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def remember(name, host, port=PORT, code=None):
    """Adds or updates a computer in the saved list (the code only when given)."""
    items = [c for c in load_computers() if not (c["host"] == host and int(c.get("port", PORT)) == int(port))]
    entry = {"name": name or host, "host": host, "port": int(port)}
    if code:
        entry["code"] = code
    items.insert(0, entry)
    save_computers(items)
    return entry


def forget(host, port=PORT):
    save_computers([c for c in load_computers() if not (c["host"] == host and int(c.get("port", PORT)) == int(port))])


def helper_path():
    return os.path.abspath(H.__file__)
