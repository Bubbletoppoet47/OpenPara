"""PDF editor, the AI-text check (pe_aipacks.py, pe_aidet.py, pe_aicheck.py, pe_aipanel.py and its parts in pe_deps.py, pe_view.py and pe_reader.py).

No real model can be fetched where this is run, so what is tried is everything around the models, with real onnxruntime and tokenizers running tiny stand-in
models that are built here (a table of next-word scores per word - the same shape of file, the same inputs and outputs, the same maths):
  * the downloads, against a local server that behaves like the Hugging Face Hub (a redirect with the size and SHA-256 in its headers, ranges, a 404, a damaged
    file, a cut connection): checked, resumed after Stop, a name that is not there tried under its other name, a disk that is too small, another download running;
  * the arithmetic of Binoculars and of Fast-DetectGPT against a plain float64 re-working of the formulas (and the Fast-DetectGPT mean and variance against a
    Monte-Carlo sampling of what they describe), over texts longer than one chunk; the input feed for models that also ask for positions, token types, an empty
    key/value cache or a cache switch; a file that only gives the last position's scores; two models that do not share their word pieces;
  * the paragraphs: one block = one paragraph, page numbers and running heads left out, a sentence that runs over a page, a heading apart from its text, short
    paragraphs joined until they are long enough, a long paragraph cut at sentence ends, texts that are too short;
  * the runner (caching, Stop, a test that fails, a test that raises) and the counting ("k of m tests lean AI", per paragraph and over the whole PDF);
  * the window: the panel, asking before downloading and before a test that needs more memory than is free, the shading (drawn and checked), a click on a
    paragraph, next/previous flagged, the numbers saved to a .csv, Stop and going on, a test that cannot be had while the others still run, Clear, and that
    nothing of it ever reaches the PDF.
What no test here can say: how well any of the three tests tells human from AI writing (that needs real models and texts whose author is known), where their
lines belong, or how fast the real models are."""
import faulthandler
import hashlib
import http.server
import json
import os
import random
import shutil
import sys
import tempfile
import threading
import time
import types
import urllib.parse

faulthandler.dump_traceback_later(280, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "pdf_editor"), os.path.join(HERE, "shared"), HERE]
import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import pymupdf
from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors

import pe_aicheck
import pe_aidet
import pe_aipacks
import pe_deps
import pe_pdfio as pio
import pe_reader
import pe_speech
import pe_store
import pe_text

T = tempfile.mkdtemp(prefix="opara_ai_")
MODELS = os.path.join(T, "ai_check")
pe_aipacks.models_root = lambda: MODELS
pe_aipacks.shutil.disk_usage = lambda p: types.SimpleNamespace(total=10 ** 13, used=0, free=10 ** 13)      # (a 5 GB model needs room; one test puts a small disk back)


def until(cond, seconds=20, ui=True):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if ui:
            app.processEvents()
        if cond():
            return True
        QTest.qWait(15) if ui else time.sleep(0.01)
    raise SystemExit("timed out: " + str(cond))


def raises(fn, exc=Exception, text=None):
    try:
        fn()
    except exc as e:
        assert text is None or text in str(e), (text, str(e))
        return e
    raise AssertionError("did not raise " + str(exc))


# ======================================================================================================================= the stand-in models
WORDS = ("the of and to a in is that it was for on are as with his they at be this from have or by one had not but what all were when we there can an your "
         "which their said if do will each about how up out them then she many some so these would other into has more her two like him see time could no make than "
         "first been its who now people my made over did down only way find use may water long little very after words called just where most know").split()
WORDS = list(dict.fromkeys(WORDS))
VOCAB = ["[UNK]", "<s>"] + WORDS
V = len(VOCAB)
WID = {w: i for i, w in enumerate(VOCAB)}


def make_tokenizer(path, unk_only_digits=False):
    """Words are lower-cased, full stops and commas are dropped, then each word is one token and every text starts with <s> (like Llama's tokenizer)."""
    tk = Tokenizer(models.WordLevel({w: i for i, w in enumerate(VOCAB)}, unk_token="[UNK]"))
    tk.normalizer = normalizers.Sequence([normalizers.Lowercase(), normalizers.Replace(".", ""), normalizers.Replace(",", "")])
    tk.pre_tokenizer = pre_tokenizers.Whitespace()
    tk.post_processor = processors.TemplateProcessing(single="<s> $A", special_tokens=[("<s>", 1)])
    tk.save(path)


def lm_model(E, W, extras=(), last_only=False):
    """logits = E[token] @ W : a next-word score table, with the inputs and the output of a causal language model's ONNX file."""
    i64 = TensorProto.INT64
    ins = [helper.make_tensor_value_info("input_ids", i64, ["batch_size", "sequence_length"]),
           helper.make_tensor_value_info("attention_mask", i64, ["batch_size", "total_sequence_length"])]
    if "position_ids" in extras:
        ins.append(helper.make_tensor_value_info("position_ids", i64, ["batch_size", "sequence_length"]))
    if "token_type_ids" in extras:
        ins.append(helper.make_tensor_value_info("token_type_ids", i64, ["batch_size", "sequence_length"]))
    if "past" in extras:
        for nm in ("past_key_values.0.key", "past_key_values.0.value"):
            ins.append(helper.make_tensor_value_info(nm, TensorProto.FLOAT, ["batch_size", 2, "past_sequence_length", 4]))
    if "flag" in extras:
        ins.append(helper.make_tensor_value_info("use_cache_branch", TensorProto.BOOL, [1]))
    inits = [numpy_helper.from_array(E.astype(np.float32), "E"), numpy_helper.from_array(W.astype(np.float32), "W")]
    nodes = [helper.make_node("Gather", ["E", "input_ids"], ["h"], axis=0), helper.make_node("MatMul", ["h", "W"], ["all_logits" if last_only else "logits"])]
    if last_only:
        inits += [numpy_helper.from_array(np.array([-1], np.int64), "st"), numpy_helper.from_array(np.array([2 ** 40], np.int64), "en"),
                  numpy_helper.from_array(np.array([1], np.int64), "ax")]
        nodes.append(helper.make_node("Slice", ["all_logits", "st", "en", "ax"], ["logits"]))
    out = helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["batch_size", 1 if last_only else "sequence_length", E.shape[0] if W.shape[1] == E.shape[0] else W.shape[1]])
    g = helper.make_graph(nodes, "lm", ins, [out], inits)
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 17)])
    m.ir_version = 8
    return m


def classifier_model(Ecls):
    """The mean of the two class scores of the words: the shape of a sequence classifier's file (input_ids, attention_mask -> logits (1, 2))."""
    i64 = TensorProto.INT64
    ins = [helper.make_tensor_value_info("input_ids", i64, ["batch_size", "sequence_length"]),
           helper.make_tensor_value_info("attention_mask", i64, ["batch_size", "sequence_length"])]
    nodes = [helper.make_node("Gather", ["Ec", "input_ids"], ["h"], axis=0), helper.make_node("ReduceMean", ["h"], ["logits"], axes=[1], keepdims=0)]
    g = helper.make_graph(nodes, "clf", ins, [helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["batch_size", 2])],
                          [numpy_helper.from_array(Ecls.astype(np.float32), "Ec")])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 17)])
    m.ir_version = 8
    return m


rs = np.random.RandomState(7)
E_OBS = rs.normal(0, 1.0, (V, 8))
W_OBS = rs.normal(0, 2.0, (8, V))
W_PERF = W_OBS + rs.normal(0, 0.25, (8, V))
E_BIG = rs.normal(0, 1.0, (V, 8))
W_BIG = rs.normal(0, 2.0, (8, V))


def greedy(E, W, n, start="the", forbid=("[UNK]", "<s>")):
    """The text the model itself would write: always the most likely next word."""
    lg = E @ W
    for f in forbid:
        lg[:, WID[f]] = -1e9
    out, cur = [], WID[start]
    for _ in range(n):
        cur = int(np.argmax(lg[cur]))
        out.append(VOCAB[cur])
    return out


STARTS = ("the", "of", "and")
CYCLE = set()
for _E, _W in ((E_OBS, W_OBS), (E_OBS, W_PERF), (E_BIG, W_BIG)):
    for _s in STARTS:
        CYCLE |= set(greedy(_E, _W, 200, start=_s)[100:])
assert 2 <= len(CYCLE) <= 30, CYCLE
E_CLS = np.zeros((V, 2))
for w in WORDS:
    E_CLS[WID[w]] = [0.0, 4.0] if w in CYCLE else [1.5, 0.0]
CONFIG = {"id2label": {"0": "Human", "1": "AI"}, "model_type": "roberta"}

# the files each repo of the pretend Hub holds, under the names the real ones have (the Qwen base model under its second name, to try the fallback)
FILES = {}
BLOBS = os.path.join(T, "blobs")
os.makedirs(BLOBS)


def blob(name, builder):
    p = os.path.join(BLOBS, name)
    builder(p)
    with open(p, "rb") as f:
        return f.read()


def save(m, p, external=False):
    if external:
        onnx.save_model(m, p, save_as_external_data=True, all_tensors_to_one_file=True, location=os.path.basename(p) + ".data", size_threshold=0)
    else:
        onnx.save_model(m, p)


tk_path = os.path.join(BLOBS, "tokenizer.json")
make_tokenizer(tk_path)
TOKENIZER = open(tk_path, "rb").read()
REPO = {"classifier": "onnx-community/tmr-ai-text-detector-ONNX", "qwen05": "onnx-community/Qwen2.5-0.5B", "qwen05i": "onnx-community/Qwen2.5-0.5B-Instruct",
        "mistral7": "EmbeddedLLM/mistral-7b-instruct-v0.3-onnx-cpu-int4-rtn-block-32-acc-level-4"}
assert {p.repo for p in pe_aipacks.PACKS.values()} == set(REPO.values()) and {k: p.repo for k, p in pe_aipacks.PACKS.items()} == REPO
FILES[REPO["classifier"] + "/onnx/model_quantized.onnx"] = blob("clf.onnx", lambda p: save(classifier_model(E_CLS), p))
FILES[REPO["classifier"] + "/tokenizer.json"] = TOKENIZER
FILES[REPO["classifier"] + "/config.json"] = json.dumps(CONFIG).encode()
FILES[REPO["qwen05"] + "/onnx/model_int8.onnx"] = blob("q.onnx", lambda p: save(lm_model(E_OBS, W_OBS, extras=("position_ids", "past")), p))
FILES[REPO["qwen05"] + "/tokenizer.json"] = TOKENIZER
FILES[REPO["qwen05i"] + "/onnx/model_quantized.onnx"] = blob("qi.onnx", lambda p: save(lm_model(E_OBS, W_PERF, extras=("position_ids", "past")), p))
FILES[REPO["qwen05i"] + "/tokenizer.json"] = TOKENIZER
big_dir = os.path.join(BLOBS, "big")
os.makedirs(big_dir)
save(lm_model(E_BIG, W_BIG, extras=("position_ids", "past", "flag")), os.path.join(big_dir, "model.onnx"), external=True)
FILES[REPO["mistral7"] + "/model.onnx"] = open(os.path.join(big_dir, "model.onnx"), "rb").read()
FILES[REPO["mistral7"] + "/model.onnx.data"] = open(os.path.join(big_dir, "model.onnx.data"), "rb").read() + b"\0" * 3_500_000      # (padding: room for a download to be stopped half way)
FILES[REPO["mistral7"] + "/tokenizer.json"] = TOKENIZER
FILES["scratch/blob/big.bin"] = bytes(random.Random(3).getrandbits(8) for _ in range(3_300_000))


# ======================================================================================================================= a pretend Hugging Face Hub
class HubHandler(http.server.BaseHTTPRequestHandler):
    log = []
    hide = set()               # repos that answer 404
    corrupt = set()            # keys whose bytes are changed on the way (same length)
    cut = {}                   # key -> how many bytes are sent before the connection is dropped
    no_range = False

    def log_message(self, *a):
        pass

    @staticmethod
    def sha(data):
        return hashlib.sha256(data).hexdigest()

    def answer(self, head):
        path = urllib.parse.unquote(self.path.split("?")[0])
        HubHandler.log.append((self.command, path, self.headers.get("Range")))
        if path.startswith("/cdn/"):
            return self.body(path[5:], head)
        if "/resolve/main/" in path:
            repo, rest = path[1:].split("/resolve/main/", 1)
            key = repo + "/" + rest
            if repo in HubHandler.hide or key not in FILES:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data = FILES[key]
            if key.endswith((".onnx", ".data", ".bin")):
                self.send_response(302)
                self.send_header("Location", "/cdn/" + key)
                self.send_header("x-linked-size", str(len(data)))
                self.send_header("x-linked-etag", '"%s"' % self.sha(data))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self.body(key, head)
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def body(self, key, head):
        data = FILES[key]
        full = len(data)
        if key in HubHandler.corrupt:
            data = bytes(b ^ 0x5A for b in data)
        start, code = 0, 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes=") and not HubHandler.no_range:
            start = int(rng[6:].split("-")[0])
            code = 206
        chunk = data[start:]
        self.send_response(code)
        self.send_header("Content-Length", str(len(chunk)))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{full - 1}/{full}")
        self.end_headers()
        if head:
            return
        n = HubHandler.cut.get(key)
        try:
            self.wfile.write(chunk if n is None else chunk[:n])
        except (ConnectionResetError, BrokenPipeError):                # (the client stopped listening: a Stop)
            pass

    def do_GET(self):
        self.answer(False)

    def do_HEAD(self):
        self.answer(True)


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HubHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
pe_aipacks.HUB = f"http://127.0.0.1:{server.server_address[1]}/"


def clean_log():
    HubHandler.log.clear()


# ======================================================================================================================= 1. downloads
assert pe_aipacks.hub_url("a/b", "x/y.onnx") == pe_aipacks.HUB + "a/b/resolve/main/x/y.onnx"
m = pe_aipacks.head_meta(pe_aipacks.hub_url(REPO["classifier"], "onnx/model_quantized.onnx"))
data = FILES[REPO["classifier"] + "/onnx/model_quantized.onnx"]
assert m == {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}, m            # the size and hash the Hub states in its first answer
m = pe_aipacks.head_meta(pe_aipacks.hub_url(REPO["classifier"], "config.json"))
assert m["size"] == len(FILES[REPO["classifier"] + "/config.json"]) and m["sha256"] is None, m       # a small file has no SHA-256 in its headers
raises(lambda: pe_aipacks.head_meta(pe_aipacks.hub_url(REPO["classifier"], "nothing.onnx")), pe_aipacks.NotFound)

assert not pe_aipacks.pack_ready("classifier") and pe_aipacks.total_mb(["classifier", "qwen05"]) == 130 + 520
clean_log()
progress = []
pe_aipacks.install_pack("classifier", lambda t, f=None: progress.append((t, f)))
assert pe_aipacks.pack_ready("classifier")
for name in ("model.onnx", "tokenizer.json", "config.json", "pack.json"):
    assert os.path.exists(pe_aipacks.file_path("classifier", name)), name
assert open(pe_aipacks.file_path("classifier", "model.onnx"), "rb").read() == data, "the file is the one that was served, under the local name"
assert not [f for f in os.listdir(pe_aipacks.pack_dir("classifier")) if f.endswith((".part", ".tmp"))]
rec = json.load(open(pe_aipacks.file_path("classifier", "pack.json")))
assert rec["files"]["model.onnx"]["sha256"] == hashlib.sha256(data).hexdigest() and rec["files"]["config.json"]["sha256"] is None
assert any("Checking" in t for t, f in progress) and any("Downloading" in t and "MB" in t for t, f in progress)
assert pe_aipacks.total_mb(["classifier", "qwen05"]) == 520, "what is there is not counted again"
clean_log()
pe_aipacks.install_pack("classifier")
assert not HubHandler.log, "a pack that is complete asks the server for nothing"
os.remove(pe_aipacks.file_path("classifier", "tokenizer.json"))
assert not pe_aipacks.pack_ready("classifier")
clean_log()
pe_aipacks.install_pack("classifier")
assert pe_aipacks.pack_ready("classifier") and not any("model_quantized" in p and c == "GET" for c, p, r in HubHandler.log), "only the file that is missing is fetched again"

# the base model keeps its file under the second name: the first name is tried (404), then the second
clean_log()
pe_aipacks.install_pack("qwen05")
assert pe_aipacks.pack_ready("qwen05") and any("model_quantized.onnx" in p for c, p, r in HubHandler.log) and any("model_int8.onnx" in p for c, p, r in HubHandler.log)

# a damaged download (right size, wrong bytes): refused and removed, nothing kept
key = REPO["qwen05i"] + "/onnx/model_quantized.onnx"
HubHandler.corrupt = {key}
e = raises(lambda: pe_aipacks.install_pack("qwen05i"), RuntimeError, "damaged")
assert not pe_aipacks.pack_ready("qwen05i") and not os.path.exists(pe_aipacks.file_path("qwen05i", "model.onnx")) and not os.path.exists(pe_aipacks.file_path("qwen05i", "model.onnx.part"))
HubHandler.corrupt = set()
# a connection that ends early: the part is kept and the next try goes on from it (Range)
HubHandler.cut = {key: 300}
raises(lambda: pe_aipacks.install_pack("qwen05i"), RuntimeError, "cut off")
part = pe_aipacks.file_path("qwen05i", "model.onnx.part")
assert os.path.getsize(part) == 300 and not pe_aipacks.pack_ready("qwen05i")
HubHandler.cut = {}
clean_log()
pe_aipacks.install_pack("qwen05i")
assert pe_aipacks.pack_ready("qwen05i") and ("GET", "/cdn/" + key, "bytes=300-") in HubHandler.log, HubHandler.log
assert open(pe_aipacks.file_path("qwen05i", "model.onnx"), "rb").read() == FILES[key], "the two parts make the whole file"
# a server that does not do ranges sends everything again: the file is still right
pe_aipacks.remove_pack("qwen05i")
HubHandler.cut = {key: 300}
raises(lambda: pe_aipacks.install_pack("qwen05i"), RuntimeError, "cut off")
HubHandler.cut, HubHandler.no_range = {}, True
pe_aipacks.install_pack("qwen05i")
HubHandler.no_range = False
assert open(pe_aipacks.file_path("qwen05i", "model.onnx"), "rb").read() == FILES[key]

# Stop: the download ends at the next block and what came is kept; the next try goes on
cancel = threading.Event()
state = {"n": 0}


def stopper(text, frac=None):
    state["n"] += 1
    if "MB" in text and state["n"] >= 2:
        cancel.set()


raises(lambda: pe_aipacks.install_pack("mistral7", stopper, cancel), pe_aipacks.Cancelled)
dpart = pe_aipacks.file_path("mistral7", "model.onnx.data.part")
assert os.path.exists(dpart) and 0 < os.path.getsize(dpart) < len(FILES[REPO["mistral7"] + "/model.onnx.data"]) and not pe_aipacks.pack_ready("mistral7")
kept = os.path.getsize(dpart)
clean_log()
pe_aipacks.install_pack("mistral7")
assert pe_aipacks.pack_ready("mistral7") and any(r == f"bytes={kept}-" for c, p, r in HubHandler.log), HubHandler.log
assert open(pe_aipacks.file_path("mistral7", "model.onnx.data"), "rb").read() == FILES[REPO["mistral7"] + "/model.onnx.data"]

# nothing found under any name; the page unreachable; a disk that is too small; another download running
HubHandler.hide = {REPO["qwen05"]}
pe_aipacks.remove_pack("qwen05")
e = raises(lambda: pe_aipacks.install_pack("qwen05"), RuntimeError, "could not be found")
assert not os.path.exists(pe_aipacks.file_path("qwen05", "model.onnx"))
HubHandler.hide = set()
real_hub = pe_aipacks.HUB
pe_aipacks.HUB = "http://127.0.0.1:9/"
raises(lambda: pe_aipacks.install_pack("qwen05"), RuntimeError, "internet connection")
pe_aipacks.HUB = real_hub
real_disk = pe_aipacks.shutil.disk_usage
pe_aipacks.shutil.disk_usage = lambda p: types.SimpleNamespace(total=1, used=0, free=50_000_000)
raises(lambda: pe_aipacks.install_pack("qwen05"), RuntimeError, "not enough room")
pe_aipacks.shutil.disk_usage = real_disk
with pe_deps.exclusive():
    raises(lambda: pe_aipacks.install_pack("qwen05"), RuntimeError, "Another download")
pe_aipacks.install_pack("qwen05")
assert all(pe_aipacks.pack_ready(p) for p in ("classifier", "qwen05", "qwen05i", "mistral7"))
# a record that says a file is there while the file is gone or has changed size does not count as ready
with open(pe_aipacks.file_path("qwen05", "tokenizer.json"), "ab") as f:
    f.write(b" ")
assert not pe_aipacks.pack_ready("qwen05")
pe_aipacks.install_pack("qwen05")
assert pe_aipacks.pack_ready("qwen05")
# resuming a plain file with fetch() directly: from the middle, and when the part is longer than the file
url = pe_aipacks.hub_url("scratch/blob", "big.bin")
bigdata = FILES["scratch/blob/big.bin"]
dest = os.path.join(T, "big.part")
c2 = threading.Event()
raises(lambda: pe_aipacks.fetch(url, dest, lambda t, f=None: c2.set(), c2, len(bigdata)), pe_aipacks.Cancelled)
assert 0 < os.path.getsize(dest) < len(bigdata)
pe_aipacks.fetch(url, dest, None, None, len(bigdata))
assert open(dest, "rb").read() == bigdata
with open(dest, "ab") as f:
    f.write(b"x" * 10)
pe_aipacks.fetch(url, dest, None, None, len(bigdata))
assert open(dest, "rb").read() == bigdata, "a part longer than the file starts again"
print("1 downloads ok")

# ======================================================================================================================= 2. the arithmetic
rng = np.random.RandomState(11)


def lsm(x):
    x = x.astype(np.float64)
    x = x - x.max(-1, keepdims=True)
    return x - np.log(np.exp(x).sum(-1, keepdims=True))


def ref_binoculars(lo, lp, ids):
    n = len(ids) - 1
    po, lq = np.exp(lsm(lo))[:n], lsm(lp)[:n]
    nll = -lq[np.arange(n), ids[1:]].mean()
    x = -(po * lq).sum(-1).mean()
    return nll / x, nll, x


def ref_fast(lg, ids):
    n = len(ids) - 1
    lp = lsm(lg)[:n]
    p = np.exp(lp)
    ll = lp[np.arange(n), ids[1:]].sum()
    mu = (p * lp).sum(-1)
    var = (p * lp ** 2).sum(-1) - mu ** 2
    return (ll - mu.sum()) / np.sqrt(var.sum())


def lg_of(E, W, ids):
    return (E.astype(np.float32)[ids] @ W.astype(np.float32))


text_ai = " ".join(greedy(E_OBS, W_PERF, 100))
text_hu = " ".join(random.Random(2).choice(WORDS) for _ in range(100))
ids_ai = np.array([WID["<s>"]] + [WID[w] for w in text_ai.split()])
ids_hu = np.array([WID["<s>"]] + [WID[w] for w in text_hu.split()])
assert len(ids_ai) == 101 > 3 * pe_aidet.CHUNK, "longer than a few chunks"
for ids in (ids_ai, ids_hu, ids_hu[:20], ids_hu[:34]):
    s, ppl, x = pe_aidet.binoculars_score(lg_of(E_OBS, W_OBS, ids), lg_of(E_OBS, W_PERF, ids), ids)
    r, rn, rx = ref_binoculars(lg_of(E_OBS, W_OBS, ids), lg_of(E_OBS, W_PERF, ids), ids)
    assert abs(s - r) < 1e-4 and abs(ppl - rn) < 1e-4 and abs(x - rx) < 1e-4, (s, r, ppl, rn, x, rx)
    d = pe_aidet.fastdetect_score(lg_of(E_BIG, W_BIG, ids), ids)
    assert abs(d - ref_fast(lg_of(E_BIG, W_BIG, ids), ids)) < 1e-3, (d, ref_fast(lg_of(E_BIG, W_BIG, ids), ids))
# with the same model twice the cross-perplexity is the mean entropy of its next-word distributions
lg = lg_of(E_OBS, W_OBS, ids_hu)
_s, _p, x_same = pe_aidet.binoculars_score(lg, lg, ids_hu)
ent = -(np.exp(lsm(lg)) * lsm(lg)).sum(-1)[:-1].mean()
assert abs(x_same - ent) < 1e-4, (x_same, ent)
# which way each score points: what the model itself would write is unsurprising (low Binoculars, high Fast-DetectGPT); random words are the other way
b_ai = pe_aidet.binoculars_score(lg_of(E_OBS, W_OBS, ids_ai), lg_of(E_OBS, W_PERF, ids_ai), ids_ai)[0]
b_hu = pe_aidet.binoculars_score(lg_of(E_OBS, W_OBS, ids_hu), lg_of(E_OBS, W_PERF, ids_hu), ids_hu)[0]
ids_ai_b = np.array([WID["<s>"]] + [WID[w] for w in greedy(E_BIG, W_BIG, 100)])
f_ai = pe_aidet.fastdetect_score(lg_of(E_BIG, W_BIG, ids_ai_b), ids_ai_b)
f_hu = pe_aidet.fastdetect_score(lg_of(E_BIG, W_BIG, ids_hu), ids_hu)
assert b_ai < 0.8 < 1.0 < b_hu and f_ai > 2.0 > 0.0 > f_hu, (b_ai, b_hu, f_ai, f_hu)
# the closed form of Fast-DetectGPT is the mean and variance of the log-likelihood of words drawn from the model, summed over the positions
lgb = lg_of(E_BIG, W_BIG, ids_hu)[:30]
lpb = lsm(lgb)
pb = np.exp(lpb)
rng2 = np.random.RandomState(5)
draws = np.stack([rng2.choice(V, size=20000, p=pb[t] / pb[t].sum()) for t in range(30)])          # (30, 20000)
ll_s = lpb[np.arange(30)[:, None], draws].sum(0)
mu_f = float((pb * lpb).sum())
var_f = float(((pb * lpb ** 2).sum(-1) - (pb * lpb).sum(-1) ** 2).sum())
assert abs(ll_s.mean() - mu_f) < 0.03 * abs(mu_f) and abs(ll_s.var() - var_f) < 0.05 * var_f, (ll_s.mean(), mu_f, ll_s.var(), var_f)
# too few tokens, models that do not share a vocabulary, numbers that cannot be used
raises(lambda: pe_aidet.binoculars_score(lg_of(E_OBS, W_OBS, ids_ai[:1]), lg_of(E_OBS, W_OBS, ids_ai[:1]), ids_ai[:1]), pe_aidet.Unjudgeable)
raises(lambda: pe_aidet.fastdetect_score(lg_of(E_OBS, W_OBS, ids_ai[:1]), ids_ai[:1]), pe_aidet.Unjudgeable)
raises(lambda: pe_aidet.binoculars_score(lg_of(E_OBS, W_OBS, ids_ai)[:, :-3], lg_of(E_OBS, W_OBS, ids_ai), ids_ai), RuntimeError, "vocabulary")
bad = lg_of(E_OBS, W_OBS, ids_hu)
bad[3, 4] = np.nan
raises(lambda: pe_aidet.binoculars_score(bad, lg_of(E_OBS, W_OBS, ids_hu), ids_hu), RuntimeError, "cannot be used")
raises(lambda: pe_aidet.fastdetect_score(bad, ids_hu), RuntimeError, "cannot be used")
assert pe_aidet.fastdetect_score(np.zeros((6, 5), np.float32) + np.array([50, -1e4, -1e4, -1e4, -1e4], np.float32), np.array([0] * 6)) == 0.0, "no variance, no score"
print("2 arithmetic ok")

# ======================================================================================================================= 3. the models (real onnxruntime and tokenizers on the stand-ins)
for tid in ("classifier", "qwen05", "qwen05i", "mistral7"):
    pe_aipacks.install_pack(tid)
obs = pe_aidet.Model("qwen05")
perf = pe_aidet.Model("qwen05i")
big = pe_aidet.Model("mistral7", heavy=True)
ids = obs.encode("The words, and the people. Zzzz made water")
assert list(ids) == [WID["<s>"], WID["the"], WID["words"], WID["and"], WID["the"], WID["people"], 0, WID["made"], WID["water"]], list(ids)
assert obs.vocab() == V
got = obs.logits(ids)
assert got.shape == (len(ids), V) and np.abs(got - lg_of(E_OBS, W_OBS, ids)).max() < 1e-4, "the feed (positions, an empty key/value cache) was built from what the model asked for"
assert np.abs(big.logits(ids) - lg_of(E_BIG, W_BIG, ids)).max() < 1e-3, "a model with its weights in a second file, and a cache switch, also works"
assert len(obs.encode("the " * 900)) == pe_aidet.MAX_TOKENS, "long text is cut at the most a model is given"
# every input a real export may ask for
for extras in (("token_type_ids",), ("position_ids", "token_type_ids", "past", "flag")):
    p_ = os.path.join(T, "x.onnx")
    onnx.save(lm_model(E_OBS, W_OBS, extras=extras), p_)
    import onnxruntime as ort
    sess = ort.InferenceSession(p_, providers=["CPUExecutionProvider"])
    out = sess.run(["logits"], pe_aidet.build_feed(sess, ids))[0][0]
    assert np.abs(out - lg_of(E_OBS, W_OBS, ids)).max() < 1e-4, extras
onnx.save(lm_model(E_OBS, W_OBS, extras=("mystery",)), os.path.join(T, "y.onnx"))
m2 = lm_model(E_OBS, W_OBS)
m2.graph.input.append(helper.make_tensor_value_info("mystery", TensorProto.FLOAT, [1]))
onnx.save(m2, os.path.join(T, "y.onnx"))
raises(lambda: pe_aidet.build_feed(ort.InferenceSession(os.path.join(T, "y.onnx"), providers=["CPUExecutionProvider"]), ids), RuntimeError, "mystery")
# a file that only gives the last word's scores cannot be used for the scoring
LAST = os.path.join(MODELS, "last")
os.makedirs(LAST)
make_tokenizer(os.path.join(LAST, "tokenizer.json"))
onnx.save(lm_model(E_OBS, W_OBS, last_only=True), os.path.join(LAST, "model.onnx"))
pe_aipacks.PACKS["last"] = pe_aipacks.Pack("last", "x", "x/x", [], 1, "")
raises(lambda: pe_aidet.Model("last").logits(ids), RuntimeError, "last word")
del pe_aipacks.PACKS["last"]
# a stop given to a model that is running ends the calculation
obs.stop()
e = raises(lambda: obs.logits(ids))
obs2 = pe_aidet.Model("qwen05")
assert obs2.logits(ids).shape[0] == len(ids), "a new model starts clean"
print("3 models ok")

# ======================================================================================================================= 4. the three tests
pe_aidet.THRESHOLDS.update({"classifier": 0.5, "binoculars": 0.8, "fastdetect": 1.0})
clf, bino, fast = pe_aidet.ClassifierTest(), pe_aidet.BinocularsTest(), pe_aidet.FastDetectTest()
say = []
for t in (clf, bino, fast):
    t.load(say.append)
assert say and all(isinstance(s, str) for s in say)
assert clf.ai_index == 1 and not clf.guessed
v_ai, v_hu = clf.judge(text_ai), clf.judge(text_hu)
assert isinstance(v_ai, pe_aidet.Verdict) and v_ai.ai and not v_hu.ai and v_ai.value > 0.9 > 0.3 > v_hu.value and "AI side" in v_ai.detail and "human side" in v_hu.detail, (v_ai, v_hu)
v_ai, v_hu = bino.judge(text_ai), bino.judge(text_hu)
assert v_ai.ai and not v_hu.ai and abs(v_ai.value - b_ai) < 1e-3 and abs(v_hu.value - b_hu) < 1e-3 and "surprise" in v_ai.detail, (v_ai, v_hu, b_ai, b_hu)
text_ai_b = " ".join(greedy(E_BIG, W_BIG, 100))
v_ai, v_hu = fast.judge(text_ai_b), fast.judge(text_hu)
assert v_ai.ai and not v_hu.ai and abs(v_ai.value - f_ai) < 1e-3 and abs(v_hu.value - f_hu) < 1e-3, (v_ai, v_hu)
for t in (clf, bino, fast):
    raises(lambda: t.judge("the of"), pe_aidet.Unjudgeable)                       # two tokens: too short once cut into pieces
pe_aidet.THRESHOLDS["fastdetect"] = 1e9
assert not fast.judge(text_ai_b).ai, "the line is a setting"
pe_aidet.THRESHOLDS["fastdetect"] = 1.0
# which class is 'AI' is read from the model's own labels
assert pe_aidet.ai_label_index({"id2label": {"0": "Human", "1": "AI"}}) == (1, False)
assert pe_aidet.ai_label_index({"id2label": {"0": "machine-generated", "1": "human"}}) == (0, False)
assert pe_aidet.ai_label_index({"id2label": {"0": "fake", "1": "real"}}) == (0, False)
assert pe_aidet.ai_label_index({"id2label": {"0": "LABEL_0", "1": "LABEL_1"}}) == (1, True), "unnamed classes: the last is taken to be AI, and that is said"
assert pe_aidet.ai_label_index({}) == (1, True)
# two models that do not share their word pieces are refused
other_tok = os.path.join(MODELS, "qwen05i", "tokenizer.json")
keep_tok = open(other_tok, "rb").read()
tk = Tokenizer.from_file(other_tok)
tk.add_tokens(["extra"])
tk.save(other_tok)
b2 = pe_aidet.BinocularsTest()
raises(lambda: b2.load(), RuntimeError, "same word pieces")
open(other_tok, "wb").write(keep_tok)
# the test objects expose what the panel shows
assert [pe_aidet.CLASSES[t].heavy for t in pe_aidet.ORDER] == [False, False, True] and pe_aidet.FastDetectTest.ram_mb > 5000
assert pe_aidet.ClassifierTest.ready() and pe_aidet.ClassifierTest.missing_mb() == 0 and pe_aidet.ClassifierTest.threshold() == 0.5
for t in (clf, bino, fast):
    t.close()
    assert t.models == []
print("4 tests ok")

# ======================================================================================================================= 5. the paragraphs
prng = random.Random(9)


def para(n, per=12, end=True, rng=prng):
    ws = [rng.choice(WORDS) for _ in range(n)]
    out, new_sentence = [], True
    for i, w in enumerate(ws):
        out.append(w.capitalize() if new_sentence else w)
        new_sentence = False
        if per and ((i + 1) % per == 0 or (i == n - 1 and end)):
            out[-1] += "."
            new_sentence = True
    return " ".join(out)


def make_pdf(path, pages, footer=None):
    """pages: a list (one per page) of lists of paragraph texts; each paragraph is a text box of its own, so a block of its own."""
    d = pymupdf.open()
    for items in pages:
        p = d.new_page()
        y = 60
        for t in items:
            rc = p.insert_textbox(pymupdf.Rect(72, y, 540, 800), t, fontsize=10)
            assert rc >= 0, "the paragraph does not fit the page"
            y += (800 - y - rc) + 26
        if footer:
            p.insert_text((300, 780), footer, fontsize=9)
    d.save(path)
    d.close()


def layout_of(pages, footer=None, name="l.pdf"):
    path = os.path.join(T, name)
    make_pdf(path, pages, footer)
    doc = pymupdf.open(path)
    dt = pe_text.DocText(doc)
    return dt, pe_aidet.build_layout(dt)


def words_of(lay):
    return [w.words for w in lay.windows]


# a 100-word paragraph, three paragraphs of 30 words and one of 4, a page number: the long paragraph on its own, the short ones joined, the number left out
pa, pb, pc, pd_, pe_ = para(100), para(30), para(30), para(30), para(4)
dt, lay = layout_of([[pa, pb, pc, pd_, pe_]], footer="12")
assert words_of(lay) == [100, 94] and lay.skipped_words == 0 and lay.total_words == 194 and lay.judged_words == 194, (words_of(lay), lay.total_words)
assert lay.windows[0].text.split() == pa.split() and lay.windows[1].text.split() == (pb + " " + pc + " " + pd_ + " " + pe_).split()
assert [w.page for w in lay.windows] == [1, 1]
assert lay.window_at(0) == 0 and lay.window_at(99) == 0 and lay.window_at(100) == 1 and lay.window_at(193) == 1 and lay.window_at(194) is None, "the page number belongs to none"
assert lay.window_at(-1) is None and lay.window_at(10 ** 6) is None
w = pe_aicheck.warnings(lay)
assert len(w) == 1 and "194 words" in w[0] and "short" in w[0], w            # (under 250 words to check: the tests are even less reliable)

# a long paragraph is cut at sentence ends: 600 words of 12-word sentences -> 168, 168, 168 and a rest of 96 (long enough to be a piece)
long_p = para(600)
dt, lay = layout_of([[long_p]])
assert words_of(lay) == [168, 168, 168, 96] and lay.total_words == 600, words_of(lay)
assert all(w.text.rstrip().endswith(".") for w in lay.windows), "cut where a sentence ends"
assert " ".join(w.text for w in lay.windows).split() == long_p.split(), "no word lost or moved"
# 260 words: 168 and 92; with sentences of 30 words a rest of 75 is joined to the piece before it (a piece is never made of fewer than 80 words)
assert words_of(layout_of([[para(260)]])[1]) == [168, 92]
assert words_of(layout_of([[para(255, per=30)]])[1]) == [255]
# no full stops at all: cut by length alone
assert words_of(layout_of([[para(400, per=0, end=False)]])[1]) == [250, 150]
# 250 words or fewer are one paragraph
assert words_of(layout_of([[para(250)]])[1]) == [250] and words_of(layout_of([[para(80)]])[1]) == [80]

# a sentence that goes over the page: one paragraph, on both pages
first, second, third = para(100), para(90, end=False), para(90)
second2 = third[0].lower() + third[1:]
dt, lay = layout_of([[first, second], [second2, para(100)]], name="span.pdf")
assert words_of(lay) == [100, 180, 100] and lay.windows[1].page == 1, words_of(lay)       # (two halves of 90 words would each be a paragraph of their own if they were not one)
assert lay.windows[1].text.split() == (second + " " + second2).split()
assert {pno for pno, _r in dt.rects_for_tokens(*lay.windows[1].runs[0])} | {pno for a, b in lay.windows[1].runs[1:] for pno, _r in dt.rects_for_tokens(a, b)} == {0, 1}

# a heading is not part of the paragraph below it (and is left out as too short); a two-word title and a page number are not even counted as left out
head = "A short heading for the section"
dt, lay = layout_of([[head, para(100)]], name="head.pdf")
assert words_of(lay) == [100] and lay.skipped_words == 6 and lay.total_words == 106
dt, lay = layout_of([["Chapter One", para(100)]], footer="7", name="head2.pdf")
assert words_of(lay) == [100] and lay.skipped_words == 0 and lay.total_words == 102

# short paragraphs are joined once they come to 160 words (or the end); what is left at the end, or between long ones, and is under 80 words, is left out
dt, lay = layout_of([[para(30) for _ in range(5)]], name="s5.pdf")
assert words_of(lay) == [150] and lay.skipped_words == 0
dt, lay = layout_of([[para(30) for _ in range(7)]], name="s7.pdf")
assert words_of(lay) == [180] and lay.skipped_words == 30
dt, lay = layout_of([[para(30), para(100), para(30)]], name="s3.pdf")
assert words_of(lay) == [100] and lay.skipped_words == 60, (words_of(lay), lay.skipped_words)

# too short, short, nothing to read
dt, lay = layout_of([[para(50)]], name="short.pdf")
assert lay.windows == [] and lay.total_words == 50
w = pe_aicheck.warnings(lay)
assert len(w) == 1 and "Too short to judge" in w[0] and "50 words" in w[0], w
dt, lay = layout_of([[para(85)]], name="short2.pdf")
w = pe_aicheck.warnings(lay)
assert words_of(lay) == [85] and len(w) == 1 and "short" in w[0] and "85 words" in w[0], w
d0 = pymupdf.open()
d0.new_page()
p0 = os.path.join(T, "blank.pdf")
d0.save(p0)
lay = pe_aidet.build_layout(pe_text.DocText(pymupdf.open(p0)))
w = pe_aicheck.warnings(lay)
assert lay.windows == [] and lay.total_words == 0 and len(w) == 1 and "no text" in w[0], w
dt, lay = layout_of([[para(100)], [para(100)], [para(100)]], name="ok2.pdf")
assert pe_aicheck.warnings(lay) == [] and len(lay.windows) == 3 and [w.page for w in lay.windows] == [1, 2, 3]
print("5 paragraphs ok")

# ======================================================================================================================= 6. the runner
WIN = layout_of([[para(100) for _ in range(3)], [para(100) for _ in range(3)]], name="six.pdf")[1]
assert len(WIN.windows) == 6


class Fake:
    def __init__(self, tid, rule=None, delay=0.0, load_error=None):
        self.id, self.name, self.delay, self.load_error = tid, "Fake " + tid, delay, load_error
        self.rule = rule or (lambda text, n: 0.9 if n % 2 else 0.1)
        self.calls, self.stopped, self.closed, self.loaded = [], False, False, False

    def load(self, say=None):
        if self.load_error:
            raise RuntimeError(self.load_error)
        if say:
            say("loading " + self.id)
        self.loaded = True

    def judge(self, text):
        self.calls.append(text)
        if self.delay:
            time.sleep(self.delay)
        r = self.rule(text, len(self.calls))
        return pe_aidet.Verdict(r, r > 0.5, f"fake {r:.2f}")

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


def runner_with(fakes, results=None, errors=None, ids=None, layout=WIN):
    made = {f.id: f for f in fakes}
    prog = []
    r = pe_aicheck.Runner(layout, {} if results is None else results, {} if errors is None else errors, ids or list(made), make=lambda tid: made[tid],
                          progress=lambda t, f=None: prog.append((t, f)))
    return r, made, prog


# everything is judged, in order, each test closed after its turn, progress says where it is
res, err = {}, {}
fa, fb = Fake("classifier"), Fake("binoculars", delay=0.02)
r, made, prog = runner_with([fa, fb], res, err)
r.go()
assert not r.stopped and not err and all(len(res[t]) == 6 and all(isinstance(v, pe_aidet.Verdict) for v in res[t]) for t in ("classifier", "binoculars"))
assert [x.text for x in WIN.windows] == fa.calls and fa.loaded and fa.closed and fb.closed
assert [v.ai for v in res["classifier"]] == [True, False, True, False, True, False]
assert any("paragraph 3 of 6" in t for t, f in prog) and any("left" in t for t, f in prog if t.startswith("Fake binoculars")), prog[:12]
assert prog[-1][1] == 1.0 and all(0 <= f <= 1 for t, f in prog if f is not None) and [f for t, f in prog if f is not None] == sorted(f for t, f in prog if f is not None)
# a second run does nothing again; a paragraph with no result is the only one done again; a test added later runs on its own
fa2 = Fake("classifier")
r, made, prog = runner_with([fa2, Fake("fastdetect")], res, err, ids=["classifier", "fastdetect"])
r.go()
assert fa2.calls == [] and not fa2.loaded and len(res["fastdetect"]) == 6
res["classifier"][2] = None
fa3 = Fake("classifier")
r, made, prog = runner_with([fa3], res, err, ids=["classifier"])
r.go()
assert fa3.calls == [WIN.windows[2].text] and isinstance(res["classifier"][2], pe_aidet.Verdict)

# a paragraph that is too short for a test once it is cut into pieces gets no result from it (and is not asked again)
def short_rule(text, n):
    if n == 2:
        raise pe_aidet.Unjudgeable("x")
    return 0.9


res, err = {}, {}
f = Fake("classifier", short_rule)
r, made, prog = runner_with([f], res, err, ids=["classifier"])
r.go()
assert res["classifier"][1] is False and not err and sum(isinstance(v, pe_aidet.Verdict) for v in res["classifier"]) == 5
f = Fake("classifier")
r, made, prog = runner_with([f], res, err, ids=["classifier"])
r.go()
assert f.calls == [] and not f.loaded, "False means 'tried'"

# Stop: from another thread, between two paragraphs - or at once, the running test is told to give up; what was done is kept; going on later finishes the rest
res, err = {}, {}
stop_after = {"n": 3}
holder = {}


def stopping(text, n):
    if n == stop_after["n"]:
        holder["r"].stop()
    return 0.9


f1, f2 = Fake("classifier", stopping), Fake("binoculars")
r, made, prog = runner_with([f1, f2], res, err)
holder["r"] = r
r.go()
assert r.stopped and f1.stopped and f1.closed and len(f1.calls) == 3 and not f2.calls and not f2.loaded, (f1.calls, f2.calls)
assert [isinstance(v, pe_aidet.Verdict) for v in res["classifier"]] == [True, True, True, False, False, False] or [v is not None for v in res["classifier"]] == [True] * 3 + [False] * 3
assert not err, "a stop is not an error"
stop_after["n"] = -1
f1b, f2b = Fake("classifier"), Fake("binoculars")
r, made, prog = runner_with([f1b, f2b], res, err)
r.go()
assert len(f1b.calls) == 3 and len(f2b.calls) == 6 and not r.stopped and all(v is not None for t in res for v in res[t])
# the same from a second thread while a slow paragraph is being judged
res, err = {}, {}
slow = Fake("classifier", delay=0.15)
r, made, prog = runner_with([slow], res, err, ids=["classifier"])
th = threading.Thread(target=r.go)
th.start()
until(lambda: len(slow.calls) >= 2, ui=False)
r.stop()
th.join(5)
assert not th.is_alive() and r.stopped and slow.stopped and len(slow.calls) in (2, 3) and not err

# a test that cannot be loaded is reported and the next one runs; a test that raises in the middle keeps what it had; a stop that makes a model raise is no error
res, err = {}, {}
bad, ok = Fake("classifier", load_error="the model file is missing"), Fake("binoculars")
r, made, prog = runner_with([bad, ok], res, err)
r.go()
assert err == {"classifier": "the model file is missing"} and bad.closed and len(ok.calls) == 6 and "classifier" in res and all(v is None for v in res["classifier"])


def boom(text, n):
    if n == 4:
        raise RuntimeError("the model gave numbers that cannot be used")
    return 0.9


res, err = {}, {}
b = Fake("fastdetect", boom)
r, made, prog = runner_with([b, Fake("binoculars")], res, err, ids=["fastdetect", "binoculars"])
r.go()
assert err == {"fastdetect": "the model gave numbers that cannot be used"} and sum(isinstance(v, pe_aidet.Verdict) for v in res["fastdetect"]) == 3 and len(made["binoculars"].calls) == 6
res, err = {}, {}
r, made, prog = runner_with([Fake("fastdetect", lambda t, n: (_ for _ in ()).throw(MemoryError()))], res, err, ids=["fastdetect"])
r.go()
assert err == {"fastdetect": "ran out of memory"}, err
res, err = {}, {}


def raise_after_stop(text, n):
    holder["r"].stop()
    raise RuntimeError("Exiting due to terminate flag being set to true")


f = Fake("classifier", raise_after_stop)
r, made, prog = runner_with([f], res, err, ids=["classifier"])
holder["r"] = r
r.go()
assert not err and r.stopped
# an error from an earlier run is gone once the test is run again
err = {"classifier": "old"}
r, made, prog = runner_with([Fake("classifier")], {}, err, ids=["classifier"])
r.go()
assert err == {}
assert pe_aicheck._duration(10) == "less than a minute" and pe_aicheck._duration(125) == "about 2 minutes" and pe_aicheck._duration(60) == "about 1 minute"
assert pe_aicheck._duration(3 * 3600 + 25 * 60) == "about 3 h 25 min"
print("6 runner ok")

# ======================================================================================================================= 7. counting, the words for it, the numbers in a file
V_ = pe_aidet.Verdict
yes, no = (lambda x: V_(x, True, "d")), (lambda x: V_(x, False, "d"))
RES = {"classifier": [yes(.9), yes(.8), no(.1), no(.2), yes(.7), None],
       "binoculars": [yes(.5), no(1.2), no(1.1), no(1.3), yes(.6), False],
       "fastdetect": [yes(2.0), no(0.1), no(0.2), no(0.3), no(0.4), False]}
tl = pe_aicheck.Tally(WIN, RES, list(pe_aidet.ORDER))
assert tl.test_ids == ["classifier", "binoculars", "fastdetect"] and tl.tests_run == 3
assert tl.per_window == [(3, 3), (1, 3), (0, 3), (0, 3), (2, 3), (0, 0)], tl.per_window
assert tl.per_test["classifier"] == {"windows": 5, "ai_windows": 3, "words": 500, "ai_words": 300, "lean": True}
assert tl.per_test["binoculars"]["lean"] is False and tl.per_test["fastdetect"]["ai_windows"] == 1 and tl.leaning == 1
assert pe_aicheck.window_text(tl, 0) == "3 of 3 tests lean AI" and pe_aicheck.window_text(tl, 2) == "0 of 3 tests lean AI" and pe_aicheck.window_text(tl, 5) == "no result"
assert pe_aicheck.overall_text(tl) == "1 of 3 tests lean AI over the whole PDF"
assert pe_aicheck.count_text(1, 1) == "1 of 1 test leans AI" and pe_aicheck.count_text(0, 2) == "0 of 2 tests lean AI" and pe_aicheck.count_text(0, 0) == "no result"
line = pe_aicheck.test_line(pe_aidet.ClassifierTest, tl, "classifier")
assert line == "Trained classifier: 3 of 5 paragraphs lean AI (60% of the words) - leans AI overall", line
assert "does not lean AI overall" in pe_aicheck.test_line(pe_aidet.BinocularsTest, tl, "binoculars")
det = pe_aicheck.window_details(WIN, RES, 5, list(pe_aidet.ORDER))
assert [d[2] for d in det] == [None, None, None] and "not run" in det[0][1] and "too short to judge" in det[1][1]
det = pe_aicheck.window_details(WIN, RES, 1, list(pe_aidet.ORDER))
assert [d[2] for d in det] == [True, False, False] and det[0][1] == "Trained classifier: leans AI - d" and det[1][1].startswith("Binoculars: does not lean AI")
assert pe_aicheck.window_details(WIN, {"classifier": RES["classifier"]}, 1, ["classifier", "fastdetect"])[1][1] == "Fast-DetectGPT (7B): not run"
# a test with no verdict at all is not counted; no tests: nothing to say
tl1 = pe_aicheck.Tally(WIN, {"classifier": RES["classifier"], "binoculars": [None] * 6}, list(pe_aidet.ORDER))
assert tl1.test_ids == ["classifier"] and pe_aicheck.overall_text(tl1) == "1 of 1 test leans AI over the whole PDF" and tl1.per_window[0] == (1, 1)
tl0 = pe_aicheck.Tally(WIN, {}, list(pe_aidet.ORDER))
assert tl0.tests_run == 0 and pe_aicheck.overall_text(tl0) == "" and tl0.per_window == [(0, 0)] * 6
# exactly half of the words is not "more than half"
half = {"classifier": [yes(.9), yes(.9), yes(.9), no(.1), no(.1), no(.1)]}
assert pe_aicheck.Tally(WIN, half, ["classifier"]).per_test["classifier"]["lean"] is False
import csv
cp = os.path.join(T, "n.csv")
pe_aicheck.write_csv(cp, WIN, RES, list(pe_aidet.ORDER))
rows = list(csv.reader(open(cp, encoding="utf-8")))
assert rows[0] == ["paragraph", "page", "words", "starts with", "classifier value", "classifier leans AI", "binoculars value", "binoculars leans AI",
                   "fastdetect value", "fastdetect leans AI", "tests leaning AI"], rows[0]
assert len(rows) == 7 and rows[1][:3] == ["1", "1", "100"] and rows[1][4:] == ["0.9000", "yes", "0.5000", "yes", "2.0000", "yes", "3 of 3"], rows[1]
assert rows[3][4:] == ["0.1000", "no", "1.1000", "no", "0.2000", "no", "0 of 3"] and rows[6][4:] == ["", "", "", "", "", "", ""], rows[6]
assert rows[1][3] == " ".join(WIN.windows[0].text.split()[:8])
print("7 counting ok")

# ======================================================================================================================= 8. the window
def fmt(words, per=12):
    out, new = [], True
    for i, w in enumerate(words):
        out.append(w.capitalize() if new else w)
        new = False
        if (i + 1) % per == 0 or i == len(words) - 1:
            out[-1] += "."
            new = True
    return " ".join(out)


P = {"hu1": para(100), "ai1": fmt(greedy(E_OBS, W_PERF, 100, start="the")), "ai2": fmt(greedy(E_BIG, W_BIG, 100, start="of")),
     "hu2": para(100), "ai1b": fmt(greedy(E_OBS, W_PERF, 100, start="and")), "hu3": para(100)}
NAMES = list(P)
UIPDF = os.path.join(T, "ui.pdf")
make_pdf(UIPDF, [["Summary of findings", P["hu1"], P["ai1"], P["ai2"]], [P["hu2"], P["ai1b"], P["hu3"]]])
UIBYTES = open(UIPDF, "rb").read()
# what each test says about each paragraph, worked out directly (not through the window)
direct = {tid: pe_aidet.CLASSES[tid]() for tid in pe_aidet.ORDER}
for t in direct.values():
    t.load()
EXPECT = {n: {tid: direct[tid].judge(P[n]) for tid in pe_aidet.ORDER} for n in NAMES}
for t in direct.values():
    t.close()
for n in ("hu1", "hu2", "hu3"):
    assert not any(v.ai for v in EXPECT[n].values()), (n, EXPECT[n])
assert EXPECT["ai1"]["classifier"].ai and EXPECT["ai1"]["binoculars"].ai and EXPECT["ai2"]["classifier"].ai and EXPECT["ai2"]["fastdetect"].ai
assert any(sum(v.ai for v in EXPECT[n].values()) == 3 for n in NAMES) or any(sum(v.ai for v in EXPECT[n].values()) == 2 for n in NAMES)
print("  the paragraphs, as the tests see them directly:", {n: [int(EXPECT[n][t].ai) for t in pe_aidet.ORDER] for n in NAMES})


class Eng:
    def apply(self, *a):
        pass

    def speak(self, t):
        pass

    def purge(self):
        pass

    def pause(self):
        pass

    def resume(self):
        pass

    def wait(self, ms):
        time.sleep(ms / 1000)
        return True

    def close(self):
        pass


class Backend:
    names = ["Test David"]

    def available(self):
        return True

    def list_voices(self):
        return list(self.names)

    def engine(self):
        return Eng()


ASK, ANSWER = [], {"download": False, "memory": False}


def make_reader(path=UIPDF):
    r = pe_reader.ReaderTab(path, pe_speech.Hub(Backend()), pe_store.Store())
    r.resize(1300, 900)
    r.show()
    until(lambda: r.text.ready)
    r.ask_ai_download = lambda mb, names, heavy: (ASK.append(("download", mb, list(names), heavy)), ANSWER["download"])[1]
    r.ask_ai_memory = lambda cls, total, avail: (ASK.append(("memory", cls.id, total, avail)), ANSWER["memory"])[1]
    return r


def run_and_wait(r, ids=None, button=None):
    if button is None:
        r.ai_run(ids if ids is not None else r.ai_selected())
    else:
        button.click()
    until(lambda: not r.ai_busy, 120)


def strengths(r):
    d = {}
    for pno, rect, st, k in r.view.ai_marks:
        assert d.setdefault(k, st) == st
    return d


def expected_strengths(ids):
    return {k: sum(EXPECT[n][t].ai for t in ids) / len(ids) for k, n in enumerate(NAMES)}


def expected_overall(ids):
    k = sum(1 for t in ids if 2 * sum(1 for n in NAMES if EXPECT[n][t].ai) > len(NAMES))
    return pe_aicheck.count_text(k, len(ids), " over the whole PDF")


def clear_all_packs():
    for p in pe_aipacks.PACKS:
        pe_aipacks.remove_pack(p)


# ---- the panel, before anything is downloaded
clear_all_packs()
r = make_reader()
assert [s.title for s in r.sections] == ["Read aloud", "Highlights", "AI check", "This PDF"] and [s.number for s in r.sections] == [1, 2, 3, 4]
assert list(r.ai_checks) == ["classifier", "binoculars", "fastdetect"] and [r.ai_checks[t].isChecked() for t in pe_aidet.ORDER] == [True, True, False]
assert r.ai_checks["classifier"].text() == "Trained classifier" and r.ai_checks["fastdetect"].text() == "Fast-DetectGPT (7B)"
assert "Experimental" in r.ai_banner.text() and "not proof" in r.ai_banner.text() and "starting guess" in r.ai_banner.text() and "English" in r.ai_banner.text()
assert "Needs a download of about 130 MB, once." in r.ai_notes["classifier"].text(), r.ai_notes["classifier"].text()
assert "Needs a download of about 1.0 GB, once." in r.ai_notes["binoculars"].text()
fn = r.ai_notes["fastdetect"].text()
assert "Needs a download of about 5.0 GB" in fn and "5.6 GB of free memory" in fn and "Slow" in fn, fn
assert r.ai_b_run.isEnabled() and not r.ai_b_stop.isEnabled() and not r.ai_b_csv.isEnabled() and not r.ai_b_clear.isEnabled() and not r.ai_b_next.isEnabled()
assert r.ai_summary() == "not run" and r.ai_overall.text() == "" and r.view.ai_marks == []

# no test ticked; a download that is running; downloads switched off
for t in pe_aidet.ORDER:
    r.ai_checks[t].setChecked(False)
r.ai_b_run.click()
assert "Tick at least one test" in r.status.full and not r.ai_busy
for t in ("classifier", "binoculars"):
    r.ai_checks[t].setChecked(True)
with pe_deps.exclusive():
    r.ai_b_run.click()
assert "Another download is already running" in r.status.full and not r.ai_busy and not ASK
pe_reader.ReaderTab.AUTO_SETUP = False
r.ai_b_run.click()
assert "not downloaded" in r.status.full and not r.ai_busy and not ASK
pe_reader.ReaderTab.AUTO_SETUP = True

# asked first: the answer no downloads nothing and runs nothing
clean_log()
ANSWER["download"] = False
r.ai_b_run.click()
assert ASK == [("download", 130 + 1040, ["Trained classifier", "Binoculars"], False)], ASK
assert not r.ai_busy and "Nothing was downloaded" in r.status.full and not HubHandler.log and not os.path.exists(pe_aipacks.pack_dir("classifier"))
assert r.view.ai_marks == [] and r.ai_summary() == "not run"
# yes: the packs are fetched, then both tests run over all six paragraphs
ASK.clear()
ANSWER["download"] = True
statuses = []
r.sig.ai_progress.connect(lambda t, f: statuses.append(t))
run_and_wait(r, button=r.ai_b_run)
assert ASK == [("download", 1170, ["Trained classifier", "Binoculars"], False)]
assert pe_aipacks.pack_ready("classifier") and pe_aipacks.pack_ready("qwen05") and pe_aipacks.pack_ready("qwen05i") and not pe_aipacks.pack_ready("mistral7")
assert any(s.startswith("Downloading") for s in statuses) and any("paragraph 6 of 6" in s for s in statuses) and not r.ai_errors, (statuses[:5], r.ai_errors)
assert len(r.ai_layout.windows) == 6 and [w.text.split() for w in r.ai_layout.windows] == [P[n].split() for n in NAMES]
ids2 = ["classifier", "binoculars"]
for tid in ids2:
    got = r.ai_results[tid]
    assert len(got) == 6 and all(isinstance(v, pe_aidet.Verdict) for v in got)
    for k, n in enumerate(NAMES):
        assert got[k].ai == EXPECT[n][tid].ai and abs(got[k].value - EXPECT[n][tid].value) < 1e-6, (tid, n, got[k], EXPECT[n][tid])
assert strengths(r) == expected_strengths(ids2), (strengths(r), expected_strengths(ids2))
assert r.ai_overall.text() == expected_overall(ids2) + " (6 paragraphs checked)", r.ai_overall.text()
assert r.ai_summary() == expected_overall(ids2) and len(r.ai_tests_lbl.text().splitlines()) == 2 and r.ai_tests_lbl.text().startswith("Trained classifier: ")
assert "Done: " + expected_overall(ids2) in r.status.full, r.status.full
assert r.ai_warn.text() == "" or "short" in r.ai_warn.text()                       # (600 words are long enough: no warning)
assert r.ai_warn.text() == "", r.ai_warn.text()
assert "Downloaded." in r.ai_notes["classifier"].text() and "Downloaded." in r.ai_notes["binoculars"].text() and "Needs a download" in r.ai_notes["fastdetect"].text()
assert r.ai_b_run.isEnabled() and not r.ai_b_stop.isEnabled() and r.ai_b_csv.isEnabled() and r.ai_b_clear.isEnabled() and r.ai_timer.isActive() is False
assert all(r.ai_checks[t].isEnabled() for t in pe_aidet.ORDER)
# nothing reached the PDF
assert open(UIPDF, "rb").read() == UIBYTES and not r.is_dirty() and r.edits.count() == 0 and r.title() == "ui.pdf"

# the shading is drawn: purple where tests lean AI (deeper with more of them), a faint green where none does, nothing on other text
def mean_rgb(img, rect):
    x0, y0, x1, y1 = (int(round(v)) for v in (rect.left(), rect.top(), rect.right(), rect.bottom()))
    tot, n = [0, 0, 0], 0
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            c = QColor(img.pixel(x, y))
            tot[0] += c.red()
            tot[1] += c.green()
            tot[2] += c.blue()
            n += 1
    return [t / n for t in tot]


def sheet_rect(k):
    pno, rc = r.ai_window_rects(k)[0]
    return r.view.to_sheet(pno, rc)


with_marks = r.view.sheet.grab().toImage()
saved_marks = r.view.ai_marks
r.view.ai_marks = []
without = r.view.sheet.grab().toImage()
r.view.ai_marks = saved_marks
st = expected_strengths(ids2)
hi = max(st, key=st.get)
lo = min(st, key=st.get)
assert st[hi] > 0 and st[lo] == 0, st
a, b = mean_rgb(with_marks, sheet_rect(hi)), mean_rgb(without, sheet_rect(hi))
assert a[1] < b[1] - 8 and a[0] < b[0] - 1, (a, b)                    # purple: green is taken out
a, b = mean_rgb(with_marks, sheet_rect(lo)), mean_rgb(without, sheet_rect(lo))
assert a[0] < b[0] - 5 and (b[1] - a[1]) < 0.6 * (b[0] - a[0]) and a[1] > a[0], (a, b)    # faint green: red goes down most, green least
mid = [k for k in st if 0 < st[k] < st[hi]]
if mid:
    am, ah = mean_rgb(with_marks, sheet_rect(mid[0])), mean_rgb(with_marks, sheet_rect(hi))
    assert am[1] > ah[1], "fewer tests leaning AI: lighter"
heading = [t for t in r.text.tokens if t.text == "Summary"][0]
hp, hr = heading.parts[0]
hs = r.view.to_sheet(hp, hr)
assert mean_rgb(with_marks, hs) == mean_rgb(without, hs), "text that was not checked is not shaded"

# a click on a paragraph shows what each test said about it, and the reading marker moves as it always did
for k, n in enumerate(NAMES):
    pno, rc = r.ai_window_rects(k)[0]
    r.view.scroll_to(r.view.page_y[pno] + rc[1] * r.view.scale - 100)
    app.processEvents()
    q = r.view.to_sheet(pno, rc).center().toPoint()
    QTest.mouseClick(r.view.sheet, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, q)
    assert r.view.ai_focus == k and r.view.read_idx is not None, (k, r.view.ai_focus)
    lines = r.ai_detail.text().splitlines()
    ai, m = r.ai_tally.per_window[k]
    assert lines[0] == f"Paragraph on page {1 if k < 3 else 2} (100 words): {pe_aicheck.count_text(ai, m)}", lines[0]
    assert len(lines) == 3 and lines[1].startswith("Trained classifier: ") and lines[2].startswith("Binoculars: ")
    assert ("leans AI" in lines[1] and "does not" not in lines[1]) == EXPECT[n]["classifier"].ai
hp2, hr2 = heading.parts[0]
r.view.scroll_to(0)
app.processEvents()
QTest.mouseClick(r.view.sheet, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.view.to_sheet(hp2, hr2).center().toPoint())
assert r.view.ai_focus is None and r.ai_detail.text() == "", "a click outside the checked paragraphs clears the detail"
QTest.mouseClick(r.view.sheet, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.view.to_sheet(0, (5, 5, 6, 6)).center().toPoint())
assert r.view.ai_focus is None

# next / previous flagged paragraph, going round at the ends, and the window follows
flagged = [k for k in range(6) if r.ai_tally.per_window[k][0] > 0]
assert flagged and r.ai_b_next.isEnabled() and r.ai_b_prev.isEnabled()
seen = []
r.view.scroll_to(0)
for _ in range(len(flagged)):
    r.ai_b_next.click()
    seen.append(r.view.ai_focus)
    pno, rc = r.ai_window_rects(r.view.ai_focus)[0]
    y = r.view.page_y[pno] + rc[1] * r.view.scale
    top = r.view.verticalScrollBar().value()
    assert top - 1 <= y <= top + r.view.viewport().height(), "the paragraph is brought into view"
assert seen == flagged, (seen, flagged)
r.ai_b_next.click()
assert r.view.ai_focus == flagged[0] and "Went round" in r.status.full
r.ai_b_prev.click()
assert r.view.ai_focus == flagged[-1] and "Went round" in r.status.full
r.ai_b_prev.click()
assert r.view.ai_focus == (flagged[-2] if len(flagged) > 1 else flagged[-1])
# from where the window is, when no paragraph is chosen
r.view.ai_focus = None
r.view.scroll_to_page(1)
app.processEvents()
r.ai_b_next.click()
assert r.view.ai_focus == next((k for k in flagged if r.ai_layout.windows[k].page - 1 >= r.view.current_page()), flagged[0])

# the numbers go into a .csv
import pe_aipanel
csvp = os.path.join(T, "ui.csv")
pe_aipanel.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (csvp, ""))
r.ai_b_csv.click()
rows = list(csv.reader(open(csvp, encoding="utf-8")))
assert len(rows) == 7 and rows[0][:4] == ["paragraph", "page", "words", "starts with"] and "Saved the numbers" in r.status.full
assert abs(float(rows[1][4]) - EXPECT["hu1"]["classifier"].value) < 1e-3 and abs(float(rows[2][6]) - EXPECT["ai1"]["binoculars"].value) < 1e-3
pe_aipanel.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
os.remove(csvp)
r.ai_b_csv.click()
assert not os.path.exists(csvp), "no file name: nothing is written"

# Clear removes the shading and the results; running again finds everything where it was and runs everything again
r.ai_b_clear.click()
assert r.view.ai_marks == [] and r.ai_results == {} and r.ai_summary() == "not run" and r.ai_overall.text() == "" and not r.ai_b_csv.isEnabled()
ASK.clear()
run_and_wait(r, button=r.ai_b_run)
assert not ASK and strengths(r) == expected_strengths(ids2), "downloaded files are kept: no question, same answer"

# the heavy test: asked about memory first when too little is free; no declines it and the others go on; yes runs it
real_memory = pe_aidet.memory
pe_aidet.memory = lambda: (8.0e9, 3.0e9)
ANSWER["memory"] = False
ASK.clear()
r.ai_b_clear.click()
run_and_wait(r, button=r.ai_b_all)
assert [r.ai_checks[t].isChecked() for t in pe_aidet.ORDER] == [True, True, True], "Run all ticks every test"
assert ASK == [("memory", "fastdetect", 8.0e9, 3.0e9)], ASK
assert "fastdetect" not in r.ai_results and set(r.ai_results) == {"classifier", "binoculars"} and not r.ai_errors
pe_aidet.memory = lambda: (16.0e9, 12.0e9)
ASK.clear()
run_and_wait(r, button=r.ai_b_all)
assert ASK == [("download", 5000, ["Fast-DetectGPT (7B)"], True)], ASK        # enough memory: not asked about that; the big model is not there yet: asked, and only for it
assert len(r.ai_results["fastdetect"]) == 6 and all(isinstance(v, pe_aidet.Verdict) for v in r.ai_results["fastdetect"])
ids3 = list(pe_aidet.ORDER)
assert strengths(r) == expected_strengths(ids3) and r.ai_overall.text() == expected_overall(ids3) + " (6 paragraphs checked)", (strengths(r), expected_strengths(ids3))
assert len(r.ai_tests_lbl.text().splitlines()) == 3 and "Fast-DetectGPT (7B)" in r.ai_tests_lbl.text()
pe_aidet.memory = lambda: (8.0e9, 1.0e9)                                   # every test has done every paragraph: nothing is asked, nothing is run again
ASK.clear()
run_and_wait(r, button=r.ai_b_run)
assert ASK == [] and strengths(r) == expected_strengths(ids3) and "Done" in r.status.full, ASK
pe_aidet.memory = real_memory
# a computer that cannot tell how much memory it has is not asked
pe_aidet.memory = lambda: (None, None)
ASK.clear()
r.ai_b_clear.click()
run_and_wait(r, button=r.ai_b_all)
assert not ASK and len(r.ai_results) == 3
pe_aidet.memory = real_memory
r.shutdown()
print("8a window: panel, download question, results, shading, clicks, next/previous, csv, clear, memory ok")

# ---- Stop in the middle, then go on: what was done is kept and is not done again
made = []


def slow_make(tid):
    f = Fake(tid, delay=0.25)
    made.append(f)
    return f


r = make_reader()
r.AI_MAKE = slow_make
r.ai_b_run.click()
until(lambda: sum(len(f.calls) for f in made) >= 2)
assert r.ai_busy and r.ai_b_stop.isEnabled() and not r.ai_b_run.isEnabled() and not r.ai_b_all.isEnabled() and not any(cb.isEnabled() for cb in r.ai_checks.values())
assert not r.ai_b_clear.isEnabled() and r.ai_timer.isActive()
n_before = len(made)
r.ai_run(["classifier"])                                    # pressed again while it runs: ignored
assert len(made) == n_before
until(lambda: "So far: " in r.ai_overall.text() or sum(len(f.calls) for f in made) >= 3, 5)
r.ai_b_stop.click()
assert "Stopping" in r.status.full
until(lambda: not r.ai_busy)
done1 = sum(len(f.calls) for f in made)
assert 2 <= done1 < 12 and "Stopped" in r.status.full and not r.ai_errors and not r.ai_timer.isActive() and r.ai_runner is None
assert sum(isinstance(v, pe_aidet.Verdict) for t in r.ai_results for v in r.ai_results[t]) == done1 and r.view.ai_marks, "what was done is shown"
assert r.ai_b_run.isEnabled() and not r.ai_b_stop.isEnabled() and all(cb.isEnabled() for cb in r.ai_checks.values())
made2 = []
r.AI_MAKE = lambda tid: (made2.append(Fake(tid)), made2[-1])[1]
run_and_wait(r, button=r.ai_b_run)
assert sum(len(f.calls) for f in made2) == 12 - done1, (done1, [len(f.calls) for f in made2])
assert sum(isinstance(v, pe_aidet.Verdict) for t in r.ai_results for v in r.ai_results[t]) == 12 and "Done" in r.status.full
r.shutdown()

# ---- Closing the tab while it runs ends the work
made = []
r = make_reader()
r.AI_MAKE = slow_make
r.ai_b_run.click()
until(lambda: sum(len(f.calls) for f in made) >= 1)
runner = r.ai_runner
r.shutdown()
assert runner.cancel.is_set() and r.ai_cancel.is_set() and not r.ai_timer.isActive()
until(lambda: not r.ai_busy)

# ---- one test cannot be had (its model page does not answer): that is said, the other test still runs, and a later run fetches it
pe_aipacks.remove_pack("qwen05")
HubHandler.hide = {REPO["qwen05"]}
ANSWER["download"] = True
ASK.clear()
r = make_reader()
run_and_wait(r, button=r.ai_b_run)
assert ASK == [("download", 520, ["Binoculars"], False)], ASK
assert set(r.ai_results) == {"classifier"} and "could not be found" in r.ai_errors["binoculars"] and not pe_aipacks.pack_ready("qwen05")
assert r.ai_warn.text().startswith("Binoculars could not run: ") and "Some tests could not run" in r.status.full
assert r.ai_overall.text() == expected_overall(["classifier"]) + " (6 paragraphs checked)" and strengths(r) == expected_strengths(["classifier"])
assert r.ai_summary() == expected_overall(["classifier"])
HubHandler.hide = set()
ASK.clear()
run_and_wait(r, button=r.ai_b_run)
assert not r.ai_errors and r.ai_warn.text() == "" and set(r.ai_results) == {"classifier", "binoculars"} and pe_aipacks.pack_ready("qwen05")
assert strengths(r) == expected_strengths(ids2)
r.shutdown()

# ---- a stopped download: Stop ends it, what came is kept, no results are made
pe_aipacks.remove_pack("mistral7")
ANSWER["download"] = True
ASK.clear()
gate = {"n": 0}
orig_fetch = pe_aipacks.fetch


def slow_fetch(url, dest, progress=None, cancel=None, size=None):
    def p(text, frac=None):
        gate["n"] += 1
        time.sleep(0.2)
        if progress:
            progress(text, frac)
    return orig_fetch(url, dest, p, cancel, size)


r = make_reader()
r.AI_GETTER = slow_fetch
r.ai_checks["classifier"].setChecked(False)
r.ai_checks["binoculars"].setChecked(False)
r.ai_checks["fastdetect"].setChecked(True)
pe_aidet.memory = lambda: (16.0e9, 12.0e9)
r.ai_b_run.click()
until(lambda: gate["n"] >= 3)
r.ai_b_stop.click()
until(lambda: not r.ai_busy)
assert "Stopped" in r.status.full and r.ai_results == {} and not r.ai_errors and not pe_aipacks.pack_ready("mistral7")
assert os.path.exists(pe_aipacks.file_path("mistral7", "model.onnx.data.part")), "what came before the Stop is kept for the next try"
r.AI_GETTER = None
run_and_wait(r, button=r.ai_b_run)
assert pe_aipacks.pack_ready("mistral7") and len(r.ai_results["fastdetect"]) == 6 and r.ai_overall.text().startswith(pe_aicheck.count_text(
    1 if 2 * sum(EXPECT[n]["fastdetect"].ai for n in NAMES) > 6 else 0, 1, " over the whole PDF"))
pe_aidet.memory = real_memory
r.shutdown()

# ---- too short, and nothing to read: said, nothing is asked or run
ASK.clear()
r = make_reader(os.path.join(T, "short.pdf"))
r.ai_b_run.click()
assert not r.ai_busy and "Too short to judge" in r.status.full and r.ai_layout.windows == [] and not ASK and r.view.ai_marks == [] and "Too short to judge" in r.ai_warn.text()
assert r.ai_results == {} and r.ai_summary() == "not run" and not r.ai_b_csv.isEnabled()
r.shutdown()
r = make_reader(os.path.join(T, "blank.pdf"))
assert not r.banner.isHidden()
r.ai_b_run.click()
assert not r.ai_busy and "no text" in r.status.full and not ASK
r.shutdown()
# a PDF with only a little text is checked, with the warning that it is short
make_pdf(os.path.join(T, "mid.pdf"), [[para(100)], [para(100)]])
r = make_reader(os.path.join(T, "mid.pdf"))
run_and_wait(r, button=r.ai_b_run)
assert len(r.ai_layout.windows) == 2 and "short" in r.ai_warn.text() and "200 words" in r.ai_warn.text() and r.view.ai_marks
r.shutdown()

# ---- the sheets of other tabs and the viewer do not need the AI check: a viewer whose tab knows nothing of it still works
import pe_view


class NoAiTab:
    pass


assert getattr(NoAiTab(), "ai_clicked", None) is None and hasattr(pe_view.PdfView, "ai_fill")
assert pe_view.PdfView.ai_fill(0).alpha() < pe_view.PdfView.ai_fill(0.34).alpha() < pe_view.PdfView.ai_fill(0.67).alpha() < pe_view.PdfView.ai_fill(1.0).alpha()
assert pe_view.PdfView.ai_fill(0).green() > pe_view.PdfView.ai_fill(0).red() and pe_view.PdfView.ai_fill(1.0).green() < pe_view.PdfView.ai_fill(1.0).red()
print("8b window: stop and go on, closing, a test that cannot be had, a stopped download, too short ok")

# ---- the packages (tokenizers, onnxruntime) are missing as well: asked about together with the model, fetched first, then the run
real_ready = pe_deps.ai_ready
pk = {"ok": False}
pe_deps.ai_ready = lambda deep=False: pk["ok"]
inst = []


def fake_ai_installer(pins, target, progress):
    inst.append(list(pins))
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "ai_stand_in2.py"), "w").write("X = 1\n")
    pk["ok"] = True


pe_aipacks.remove_pack("classifier")
ASK.clear()
ANSWER["download"] = True
r = make_reader()
r.AI_INSTALLER = fake_ai_installer
for t in ("binoculars", "fastdetect"):
    r.ai_checks[t].setChecked(False)
r.ai_refresh_rows()
assert "Needs a download of about 150 MB, once." in r.ai_notes["classifier"].text(), r.ai_notes["classifier"].text()
run_and_wait(r, button=r.ai_b_run)
assert ASK == [("download", 150, ["Trained classifier", "a few small packages"], False)], ASK
assert inst == [["tokenizers>=0.15"]] and set(r.ai_results) == {"classifier"} and not r.ai_errors and pk["ok"]
assert strengths(r) == expected_strengths(["classifier"])
r.shutdown()
pe_deps.ai_ready = real_ready
shutil.rmtree(pe_deps.site_dir(pe_deps.AI), ignore_errors=True)
if pe_deps.site_dir(pe_deps.AI) in sys.path:
    sys.path.remove(pe_deps.site_dir(pe_deps.AI))

# ======================================================================================================================= 9. the packages of the AI check (pe_deps)
import importlib.util

assert pe_deps.AI == "pdfeditor_aicheck" and pe_deps.AI_PINS == ["tokenizers>=0.15"] and pe_deps.AI_RUNTIME_PINS == ["onnxruntime>=1.16"] and pe_deps.AI_MB == 20
assert pe_deps.ai_ready() and pe_deps.ai_ready(deep=True)
real_spec = importlib.util.find_spec
importlib.util.find_spec = lambda m, *a, **k: None if m == "tokenizers" else real_spec(m, *a, **k)
assert not pe_deps.ai_ready(), "one of the three missing: not ready"
importlib.util.find_spec = real_spec

calls = []


def fake_installer(pins, target, progress):
    calls.append((list(pins), target))
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "ai_stand_in.py"), "w").write("X = 1\n")
    if progress:
        progress("fake", None)


msgs = []
pe_deps.install_ai(lambda t, f=None: msgs.append(t), fake_installer)
site = pe_deps.site_dir(pe_deps.AI)
assert calls == [(["tokenizers>=0.15"], site + ".new")] and os.path.isfile(os.path.join(site, "ai_stand_in.py")) and not os.path.exists(site + ".new") and msgs == ["fake"]
assert site in sys.path and sys.path.index(site) > 0 and sys.path[-1] != "", "added to the search path, after what the program has"
pe_deps.add_to_path(pe_deps.AI)
assert sys.path.count(site) == 1
# it can be loaded from there
import ai_stand_in
assert ai_stand_in.X == 1
# a pack that cannot be loaded afterwards is an error; a failing installer leaves nothing behind; another download running is refused
real_ready = pe_deps.ai_ready
pe_deps.ai_ready = lambda deep=False: False
raises(lambda: pe_deps.install_ai(None, fake_installer), RuntimeError, "could not be loaded")
pe_deps.ai_ready = real_ready


def failing(pins, target, progress):
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "half.py"), "w").write("")
    raise RuntimeError("no internet")


raises(lambda: pe_deps.install_ai(None, failing), RuntimeError, "no internet")
assert not os.path.exists(site + ".new")
with pe_deps.exclusive():
    raises(lambda: pe_deps.install_ai(None, fake_installer), RuntimeError, "Another download")
assert not pe_deps.busy()

# the real installer, with a pip that only says what it was asked for: tokenizers on its own (--no-deps); onnxruntime (with numpy left out, the program has it) only when nothing has it
if os.name == "posix":
    import stat
    import paths
    log = os.path.join(T, "pip_calls.jsonl")
    fake_pip = os.path.join(T, "fakepip2.py")
    open(fake_pip, "w").write("""import json, os, sys, zipfile
a = sys.argv
dest = a[a.index("--dest") + 1]
pins = [x for x in a[2:] if not x.startswith("--") and x != dest]
open(%r, "a").write(json.dumps({"no_deps": "--no-deps" in a, "pins": pins}) + "\\n")
names = {"tokenizers": "tok_copy", "onnxruntime": "ort_copy2", "numpy": "numpy_copy2"}
for name in (["numpy"] if "--no-deps" not in a else []) + [p.split(">")[0] for p in pins]:
    with zipfile.ZipFile(os.path.join(dest, name + "-1.0-py3-none-any.whl"), "w") as z:
        z.writestr(names[name] + "/__init__.py", "X = 1\\n")
        z.writestr(name + "-1.0.dist-info/METADATA", "Name: x\\nVersion: 1.0\\n")
        z.writestr(name + "-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\n")
        z.writestr(name + "-1.0.dist-info/RECORD", "")
""" % log)
    runner = os.path.join(T, "fakepy2.sh")
    open(runner, "w").write('#!/bin/sh\nshift 2\nexec %s %s "$@"\n' % (sys.executable, fake_pip))
    os.chmod(runner, os.stat(runner).st_mode | stat.S_IEXEC)
    real_exe = paths.python_exe
    paths.python_exe = lambda: runner
    target = os.path.join(UD, "ai_target")
    pe_deps.ai_installer(pe_deps.AI_PINS, target, lambda t, f=None: None)
    got = [json.loads(l) for l in open(log)]
    assert got == [{"no_deps": True, "pins": ["tokenizers>=0.15"]}], got                      # onnxruntime is there: not asked for
    assert sorted(os.listdir(target)) == ["tok_copy", "tokenizers-1.0.dist-info"], os.listdir(target)
    os.remove(log)
    real_have = pe_deps._have
    pe_deps._have = lambda m: False if m == "onnxruntime" else real_have(m)
    target2 = os.path.join(UD, "ai_target2")
    pe_deps.ai_installer(pe_deps.AI_PINS, target2, lambda t, f=None: None)
    got = [json.loads(l) for l in open(log)]
    assert got == [{"no_deps": True, "pins": ["tokenizers>=0.15"]}, {"no_deps": False, "pins": ["onnxruntime>=1.16"]}], got
    names2 = set(os.listdir(target2))
    assert {"tok_copy", "ort_copy2"} <= names2 and "numpy_copy2" not in names2, names2         # numpy comes with the program
    pe_deps._have = real_have
    paths.python_exe = real_exe
shutil.rmtree(site, ignore_errors=True)
if site in sys.path:
    sys.path.remove(site)
print("9 packages ok")
print("ALL OK")
