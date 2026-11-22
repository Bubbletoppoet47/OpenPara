"""pe_aipacks.py - the model files of the AI-text tests (pe_aidet.py), downloaded one pack at a time, after asking.

A pack is the files of one model on the Hugging Face Hub, in ONNX form (so that onnxruntime, which the program already uses, can run them; no PyTorch):

    classifier   a RoBERTa-base text classifier trained to tell human text from AI text (about 125 MB)
    qwen05       Qwen2.5-0.5B, the base model     } the pair that Binoculars compares (about 500 MB each)
    qwen05i      Qwen2.5-0.5B-Instruct            }
    mistral7     Mistral-7B-Instruct-v0.3, 4-bit  - the heavy option (about 5 GB; Fast-DetectGPT)

Where a model keeps its files was read from its page on the Hub (nothing could be downloaded when this was written), so every file lists the names it may
have, and the one that exists is used.  What a download is checked against comes from the Hub itself: its answer to a HEAD request carries the size and, for
big files, the SHA-256 (x-linked-size / x-linked-etag).  A file is first written as `<name>.part`, which a stopped or broken download leaves in place so
that the next one goes on from there (Range), and it is renamed only when its size and hash are right.  One download at a time (pe_deps.exclusive).
"""
import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request

import pe_deps

HUB = "https://huggingface.co/"
UA = {"User-Agent": "OpenPara"}


class Cancelled(Exception):
    """The person pressed Stop."""


class NotFound(Exception):
    pass


class Pack:
    def __init__(self, pid, label, repo, files, mb, licence, note=""):
        self.id, self.label, self.repo, self.files, self.mb, self.licence, self.note = pid, label, repo, files, mb, licence, note


_ONNX_NAMES = ["onnx/model_quantized.onnx", "onnx/model_int8.onnx", "onnx/model_uint8.onnx"]      # int8 versions: the ones that are fast on a CPU
PACKS = {p.id: p for p in [
    Pack("classifier", "the AI-text classifier (RoBERTa, trained on RAID)", "onnx-community/tmr-ai-text-detector-ONNX",
         [("model.onnx", _ONNX_NAMES + ["onnx/model.onnx"]), ("tokenizer.json", ["tokenizer.json"]), ("config.json", ["config.json"])], 130, "MIT"),
    Pack("qwen05", "the small language model Qwen2.5-0.5B", "onnx-community/Qwen2.5-0.5B",
         [("model.onnx", _ONNX_NAMES), ("tokenizer.json", ["tokenizer.json"])], 520, "Apache-2.0 (the original model's; the ONNX page names none)"),
    Pack("qwen05i", "the small language model Qwen2.5-0.5B-Instruct", "onnx-community/Qwen2.5-0.5B-Instruct",
         [("model.onnx", _ONNX_NAMES), ("tokenizer.json", ["tokenizer.json"])], 520, "Apache-2.0 (the original model's; the ONNX page names none)"),
    Pack("mistral7", "the 7-billion-parameter language model Mistral-7B-Instruct-v0.3 (4-bit)",
         "EmbeddedLLM/mistral-7b-instruct-v0.3-onnx-cpu-int4-rtn-block-32-acc-level-4",
         [("model.onnx", ["model.onnx"]), ("model.onnx.data", ["model.onnx.data"]), ("tokenizer.json", ["tokenizer.json"])], 5000,
         "Apache-2.0 (the original model's)", "a converted copy of Mistral's model, made by a third party"),
]}


# ---------------------------------------------------------------------------------------------------------------------- where things are
def models_root():
    return os.path.join(os.path.dirname(pe_deps.models_dir()), "ai_check")


def pack_dir(pid):
    return os.path.join(models_root(), pid)


def file_path(pid, name):
    return os.path.join(pack_dir(pid), name)


def _record(pid):
    try:
        with open(os.path.join(pack_dir(pid), "pack.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("files"), dict) else None
    except (OSError, ValueError):
        return None


def pack_ready(pid):
    """Cheap: the pack was downloaded and checked, and its files are still there with the sizes they had."""
    rec = _record(pid)
    pack = PACKS.get(pid)
    if rec is None or pack is None:
        return False
    for local, _alts in pack.files:
        info = rec["files"].get(local)
        try:
            if not info or os.path.getsize(file_path(pid, local)) != info.get("bytes"):
                return False
        except OSError:
            return False
    return True


def total_mb(pids):
    return sum(PACKS[p].mb for p in pids if not pack_ready(p))


def remove_pack(pid):
    shutil.rmtree(pack_dir(pid), ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------------------- talking to the Hub
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def hub_url(repo, path):
    return f"{HUB}{repo}/resolve/main/{path}"


def head_meta(url):
    """{"size": int or None, "sha256": hex or None} as the Hub states them for this file; NotFound when there is no such file."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    try:
        r = opener.open(req, timeout=30)
        headers, status = r.headers, r.status
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound(url) from e
        if e.code in (301, 302, 303, 307, 308):
            headers, status = e.headers, e.code
        else:
            raise
    size = headers.get("x-linked-size")
    if size is None and status == 200:
        size = headers.get("Content-Length")
    try:
        size = int(size) if size is not None else None
    except ValueError:
        size = None
    etag = (headers.get("x-linked-etag") or "").strip().strip('"')
    return {"size": size, "sha256": etag.lower() if re.fullmatch(r"[0-9a-fA-F]{64}", etag) else None}


def fetch(url, dest, progress=None, cancel=None, size=None):
    """Downloads url into dest, going on from what dest already holds when the server allows it."""
    have = os.path.getsize(dest) if os.path.exists(dest) else 0
    if size and have > size:
        have = 0
    headers = dict(UA)
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        if have and r.status != 206:
            have = 0                                   # the server sent everything again: start over
        length = int(r.headers.get("Content-Length") or 0)
        total = size or ((length + have) if length else 0)
        got = have
        with open(dest, "ab" if have else "wb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(f"{got / 1e6:.0f} MB" + (f" of {total / 1e6:.0f} MB" if total else ""), (got / total) if total else None)


def sha256_file(path, progress=None, cancel=None):
    h = hashlib.sha256()
    done, total = 0, max(1, os.path.getsize(path))
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress("checking", done / total)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------------------------------- downloading a pack
def install_pack(pid, progress=None, cancel=None, meta=None, getter=None):
    """Downloads the files of pack `pid` that are not there yet, checks each against the size and hash the Hub states, and records the pack as complete.
    progress(text, fraction or None).  Raises Cancelled (what was downloaded is kept as .part), or RuntimeError with a sentence for the person."""
    pack = PACKS[pid]
    meta, getter = meta or head_meta, getter or fetch
    with pe_deps.exclusive():
        os.makedirs(pack_dir(pid), exist_ok=True)
        rec = _record(pid) or {"files": {}}
        rec["repo"] = pack.repo
        need = [(local, alts) for local, alts in pack.files if not _file_ok(pid, local, rec)]
        free = shutil.disk_usage(pack_dir(pid)).free
        if need and free < pack.mb * 1_000_000 * 1.1:
            raise RuntimeError(f"There is not enough room on the disk for {pack.label}: it needs about {pack.mb} MB and {free // 1_000_000} MB are free.")
        for local, alts in need:
            what = f"{pack.label} ({local})"
            url, m = None, None
            for alt in alts:
                try:
                    m = meta(hub_url(pack.repo, alt))
                    url = hub_url(pack.repo, alt)
                    break
                except NotFound:
                    continue
                except Cancelled:
                    raise
                except Exception as e:                 # noqa: BLE001
                    raise RuntimeError(f"Could not reach the model's page for {pack.label} (needs an internet connection): {e}") from e
            if url is None:
                raise RuntimeError(f"{pack.label} could not be found at {HUB}{pack.repo} (the page may have moved or changed). Nothing was downloaded.")
            dest = file_path(pid, local)
            part = dest + ".part"

            def say(text, frac=None, what=what):
                if progress:
                    progress(f"Downloading {what}: {text}" if text != "checking" else f"Checking {what} ...", frac)
            try:
                getter(url, part, say, cancel, m["size"])
            except Cancelled:
                raise
            except Exception as e:                     # noqa: BLE001
                raise RuntimeError(f"Downloading {what} stopped (needs an internet connection): {e}. The next try goes on from where it got to.") from e
            size = os.path.getsize(part)
            if m["size"] is not None and size < m["size"]:           # the connection ended early: what came is kept, the next try goes on from there
                raise RuntimeError(f"The download of {what} was cut off ({size // 1_000_000} of {m['size'] // 1_000_000} MB). "
                                   "Try again: it goes on from where it stopped.")
            if m["size"] is not None and size > m["size"]:
                os.remove(part)
                raise RuntimeError(f"The download of {what} was damaged ({size} bytes came, {m['size']} were expected). Try again.")
            digest = None
            if m["sha256"]:
                digest = sha256_file(part, lambda t, f=None: say("checking", f), cancel)
                if digest != m["sha256"]:
                    os.remove(part)
                    raise RuntimeError(f"The download of {what} was damaged (its check sum is wrong). Try again.")
            os.replace(part, dest)
            rec["files"][local] = {"bytes": size, "sha256": digest, "from": url}
            _write_record(pid, rec)
        _write_record(pid, rec)


def _file_ok(pid, local, rec):
    info = rec["files"].get(local)
    try:
        return bool(info) and os.path.getsize(file_path(pid, local)) == info.get("bytes")
    except OSError:
        return False


def _write_record(pid, rec):
    tmp = os.path.join(pack_dir(pid), "pack.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    os.replace(tmp, os.path.join(pack_dir(pid), "pack.json"))
