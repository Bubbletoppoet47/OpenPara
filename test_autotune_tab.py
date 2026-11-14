"""Autotune tab and its sound-card layer, with a pretend sound card (sounddevice itself needs PortAudio and real hardware)."""
import faulthandler
import json
import math
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "addons_src", "autotune"))
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
MSGS = []
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))

import autotune_audio as AU
import autotune_core as A
import autotune_tab as AT

FS = 48000


# ============================================================================================================ a pretend sound card
class PortAudioError(Exception):
    pass


class FakeStream:
    instances = []

    def __init__(self, **kw):
        self.kw = kw
        self.started = self.closed = self.stopped = False
        self.latency = (0.01, 0.012)
        FakeStream.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True

    def feed(self, x, block=256, channels=1):
        """Plays sound `x` into the callback block by block; returns what the callback wrote."""
        cin, cout = self.kw["channels"]
        out = []
        for i in range(0, len(x) - block + 1, block):
            ind = np.zeros((block, cin), np.float32)
            ind[:, :channels] = x[i:i + block, None]
            outd = np.zeros((block, cout), np.float32)
            self.kw["callback"](ind, outd, block, None, None)
            out.append(outd.copy())
        return np.concatenate(out)


class FakeSD:
    PortAudioError = PortAudioError

    def __init__(self, rates_ok=(48000, 44100), n_in=1, wasapi=True):
        self.rates_ok = rates_ok
        self.default = type("D", (), {"hostapi": 1})()
        self._host = [{"name": "MME", "default_input_device": 0, "default_output_device": 1},
                      {"name": "Windows WASAPI", "default_input_device": 2, "default_output_device": 3}] if wasapi else \
                     [{"name": "ALSA", "default_input_device": 0, "default_output_device": 1}]
        self._dev = [
            {"name": "Mic (MME)", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0, "default_samplerate": 44100.0},
            {"name": "Speakers (MME)", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 44100.0},
            {"name": "Mic (WASAPI)", "hostapi": 1, "max_input_channels": n_in, "max_output_channels": 0, "default_samplerate": 48000.0},
            {"name": "Headphones (WASAPI)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000.0},
            {"name": "Other mic (WASAPI)", "hostapi": 1, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 48000.0},
            {"name": "HDMI (WASAPI)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000.0},
        ] if wasapi else [
            {"name": "hw:0 mic", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 44100.0},
            {"name": "hw:0 out", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 44100.0}]
        self.Stream = FakeStream
        self.calls = []

    def query_devices(self, device=None, kind=None):
        return list(self._dev)

    def query_hostapis(self, index=None):
        return self._host if index is None else self._host[index]

    def check_input_settings(self, **kw):
        if kw["samplerate"] not in self.rates_ok:
            raise PortAudioError("Invalid sample rate")

    def check_output_settings(self, **kw):
        self.check_input_settings(**kw)


def voice(f0, n=FS, amp=0.4):
    t = np.arange(n) / FS
    return (sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 2, 3, 4, 5)) * amp / 2).astype(np.float32)


# ============================================================================================================ device lists
sd = FakeSD()
systems = AU.list_systems(sd)
assert [s["name"] for s in systems] == ["Windows WASAPI", "MME"], systems          # WASAPI first, the lowest delay
assert [d["name"] for d in AU.list_devices(sd, 1, "input")] == ["Mic (WASAPI)", "Other mic (WASAPI)"]
assert AU.list_devices(sd, 1, "input")[0]["default"] and AU.list_devices(sd, 1, "output")[0]["name"] == "Headphones (WASAPI)"
assert [s["name"] for s in AU.list_systems(FakeSD(wasapi=False))] == ["ALSA"]

# ============================================================================================================ the runner
ind, outd = AU.list_devices(sd, 1, "input")[0], AU.list_devices(sd, 1, "output")[0]
r = AU.Runner(sd)
seen = []
info = r.start(ind, outd, block=256, fmin=100.0, in_channel=None, host_name="Windows WASAPI", configure=lambda e: seen.append(e))
st = FakeStream.instances[-1]
assert r.running() and st.started and st.kw["samplerate"] == 48000 and st.kw["blocksize"] == 256 and st.kw["channels"] == (1, 2)
assert st.kw["device"] == (2, 3) and st.kw["dtype"] == "float32" and seen and seen[0] is r.engine
assert abs(info["device_ms"] - 22.0) < 1e-6 and abs(info["total_ms"] - (info["engine_ms"] + 22.0)) < 1e-6 and info["fs"] == 48000
y = st.feed(voice(215.0), 256)
assert y.shape[1] == 2 and np.array_equal(y[:, 0], y[:, 1]), "the same sound on both sides"
assert r.blocks == len(y) // 256 and r.error is None and r.engine.underruns == 0
seg = y[FS // 2:int(1.5 * FS), 0] if len(y) > int(1.5 * FS) else y[len(y) // 2:, 0]
assert np.abs(seg).max() > 0.1, "sound comes out"
r.stop()
assert not r.running() and st.stopped and st.closed
r.stop()                                                                           # twice is harmless
# a sample rate the devices do not share: the next one that both take is used
sd2 = FakeSD(rates_ok=(44100,))
r = AU.Runner(sd2)
assert r.start(AU.list_devices(sd2, 1, "input")[0], AU.list_devices(sd2, 1, "output")[0], host_name="MME")["fs"] == 44100
r.stop()
sd3 = FakeSD(rates_ok=())
try:
    AU.Runner(sd3).start(AU.list_devices(sd3, 1, "input")[0], AU.list_devices(sd3, 1, "output")[0])
    raise AssertionError("no rate should fail")
except AU.AudioError as ex:
    assert "sample rate" in str(ex)
# the card refuses to open
class Refusing(FakeSD):
    def __init__(self):
        super().__init__()
        self.Stream = lambda **kw: (_ for _ in ()).throw(PortAudioError("Device unavailable"))
sd4 = Refusing()
try:
    AU.Runner(sd4).start(AU.list_devices(sd4, 1, "input")[0], AU.list_devices(sd4, 1, "output")[0])
    raise AssertionError("an unavailable device should fail")
except AU.AudioError as ex:
    assert "Device unavailable" in str(ex) and "buffer" in str(ex)
# input channels: one channel only / the mix, from a two-channel microphone
sd5 = FakeSD(n_in=2)
r = AU.Runner(sd5)
r.start(AU.list_devices(sd5, 1, "input")[0], AU.list_devices(sd5, 1, "output")[0], in_channel=1, host_name="MME")
st = FakeStream.instances[-1]
assert st.kw["channels"] == (2, 2)
got = []
orig = r.engine.process
r.engine.process = lambda x: got.append(np.array(x)) or orig(x)
ind2 = np.zeros((256, 2), np.float32); ind2[:, 0] = 0.5; ind2[:, 1] = 0.1
st.kw["callback"](ind2, np.zeros((256, 2), np.float32), 256, None, None)
assert np.allclose(got[-1], 0.1), "channel 2 only"
r.in_channel = None
st.kw["callback"](ind2, np.zeros((256, 2), np.float32), 256, None, None)
assert np.allclose(got[-1], 0.3), "the mix"
r.engine.process = lambda x: (_ for _ in ()).throw(ValueError("boom"))
o = np.ones((256, 2), np.float32)
st.kw["callback"](ind2, o, 256, None, None)
assert not o.any() and "boom" in r.error, "an error in the engine: silence, and the reason is kept (it never reaches the sound card library)"
r.stop()
# status flags are counted
r = AU.Runner(sd)
r.start(ind, outd)
r.stream.kw["callback"](np.zeros((256, 1), np.float32), np.zeros((256, 2), np.float32), 256, None, "input overflow")
assert r.dropouts == 1
r.stop()
# the library missing: words, not a traceback
real_import = AU.importlib.import_module
AU.importlib.import_module = lambda n: (_ for _ in ()).throw(OSError("PortAudio library not found"))
try:
    AU.load_sounddevice()
    raise AssertionError
except AU.AudioError as ex:
    assert ("libportaudio2" in str(ex)) if sys.platform.startswith("linux") else ("could not be loaded" in str(ex))
AU.importlib.import_module = lambda n: (_ for _ in ()).throw(ImportError("no sounddevice"))
try:
    AU.load_sounddevice()
    raise AssertionError
except AU.AudioError as ex:
    assert "Add-ons" in str(ex)
AU.importlib.import_module = real_import

# ============================================================================================================ the window
cfg = os.path.join(UD, "autotune.json")
sd = FakeSD()
t = AT.AutotuneTab(None, sd=sd, settings_file=cfg)
t.restore_prefs()
assert t.title() == "Autotune" and not t.is_dirty() and t.can_close()
assert [t.sys_box.itemText(i) for i in range(t.sys_box.count())] == ["Windows WASAPI", "MME"]
assert t.in_box.itemText(0).startswith("Mic (WASAPI)") and t.out_box.itemText(0).startswith("Headphones (WASAPI)")
assert t.start_btn.text() == "Start" and not t.running()
assert t.scale_box.currentText() == "Chromatic (every note)" and t.key_box.currentText() == "C"
# the default scale lights every note; a key and scale light the right ones
assert all(b.isChecked() for b in t.note_btns)
t.key_box.setCurrentIndex(A.KEYS.index("D")); t.scale_box.setCurrentIndex(t.scale_box.findText("Major pentatonic"))
assert [b.text() for b in t.note_btns if b.isChecked()] == ["D", "E", "F#", "A", "B"]
assert t.allowed() == A.allowed_notes("D", "Major pentatonic")
# clicking a note makes it "the notes I tick" and the key no longer matters
t.note_btns[0].setChecked(True)
assert t.scale_box.currentText() == A.CUSTOM and not t.key_box.isEnabled() and t.allowed()[0] and t.allowed()[2]
t.scale_box.setCurrentIndex(t.scale_box.findText("Minor")); t.key_box.setCurrentIndex(A.KEYS.index("A"))
assert [b.text() for b in t.note_btns if b.isChecked()] == ["C", "D", "E", "F", "G", "A", "B"] and t.key_box.isEnabled()
# sliders and their words
t.speed.setValue(0); assert t.speed_lbl.text() == "Instant"
t.speed.setValue(150); assert t.speed_lbl.text() == "150 ms"
t.amount.setValue(80); assert t.amount_lbl.text() == "80 %"
assert "A Minor" in t.sum_key() and "150 ms" in t.sum_feel()

# start: the stream opens with the chosen things, the controls that need a restart are greyed out
t.chan_box.setCurrentIndex(0)
t.block_box.setCurrentIndex(AU.BLOCKS.index(128))
t.voice_box.setCurrentIndex(2)
assert t.start() is True and t.running() and t.start_btn.text() == "Stop"
st = FakeStream.instances[-1]
assert st.kw["blocksize"] == 128 and st.kw["samplerate"] == 48000
e = t.runner.engine
assert e.fmin == 150.0 and e.speed_ms == 150.0 and abs(e.amount - 0.8) < 1e-9 and e.allowed == A.allowed_notes("A", "Minor") and e.a4 == 440.0
assert not t.in_box.isEnabled() and not t.block_box.isEnabled() and not t.sys_box.isEnabled() and t.key_box.isEnabled() and t.speed.isEnabled()
assert "Delay about" in t.status.text() and "Listening at 48000" in t.status.text()
# live changes reach the engine
t.speed.setValue(0); assert e.speed_ms == 0.0
t.amount.setValue(100); assert e.amount == 1.0
t.bypass_box.setChecked(True); assert e.bypass is True
t.bypass_box.setChecked(False); assert e.bypass is False
t.a4_spin.setValue(432.0); assert e.a4 == 432.0
t.gate.setValue(-62); assert e.gate_db == -62.0 and t.gate_lbl.text() == "-62 dB"; t.gate.setValue(-50)
t.scale_box.setCurrentIndex(t.scale_box.findText("Major")); t.key_box.setCurrentIndex(A.KEYS.index("C"))
assert e.allowed == A.allowed_notes("C", "Major")
# sound flows, the tuner display follows
t.a4_spin.setValue(440.0)
st.feed(voice(233.08 * 2 ** (20 / 1200), 2 * FS), 128)
t.tick()
s = t.view.state
assert s["voiced"] and s["note"] in ("A3", "B3") and abs(s["hz"] - 233.08 * 2 ** (20 / 1200)) < 4 and t.view.in_db > -12, s
pix = t.view.grab()
assert not pix.isNull() and pix.width() > 300
t.resize(900, 560); t.show(); app.processEvents()
shot = os.environ.get("AUTOTUNE_SHOT")
if shot:
    t.grab().save(shot)
t.hide()
# stop
t.toggle()
assert not t.running() and t.start_btn.text() == "Start" and t.in_box.isEnabled() and st.closed and t.status.text() == "Stopped."
assert t.view.state is None
# the engine failing in the sound card thread stops the stream and says so
assert t.start()
r = t.runner
r.error = "ValueError: boom"
t.tick()
assert not t.running() and "boom" in t.status.text()
# dropouts are shown
assert t.start()
t.runner.dropouts = 3
t.tick()
assert "crackled 3" in t.status.text()
t.stop()

# the choices are kept for next time
p = json.load(open(cfg))
assert p["gate"] == -50 and p["scale"] == "Major" and p["key"] == "C" and p["speed"] == 0 and p["amount"] == 100 and p["block"] == 128 and p["input"] == "Mic (WASAPI)"
assert p["voice"].startswith("High voice") and p["system"] == "Windows WASAPI" and abs(p["a4"] - 440.0) < 1e-9
t.shutdown()
t2 = AT.AutotuneTab(None, sd=FakeSD(), settings_file=cfg)
t2.restore_prefs()
assert t2.key_box.currentText() == "C" and t2.scale_box.currentText() == "Major" and t2.speed.value() == 0 and t2.block_box.currentData() == 128
assert t2.voice_box.currentText().startswith("High voice")
t2.shutdown()
# a custom scale is kept too
t3 = AT.AutotuneTab(None, sd=FakeSD(), settings_file=cfg)
t3.scale_box.setCurrentIndex(t3.scale_box.findText(A.CUSTOM))
for i, b in enumerate(t3.note_btns):
    b.setChecked(i in (0, 4, 7))
t3.save_prefs(); t3.shutdown()
t4 = AT.AutotuneTab(None, sd=FakeSD(), settings_file=cfg)
t4.restore_prefs()
assert t4.scale_box.currentText() == A.CUSTOM and [b.text() for b in t4.note_btns if b.isChecked()] == ["C", "E", "G"]
t4.shutdown()
open(cfg, "w").write("{not json")
t5 = AT.AutotuneTab(None, sd=FakeSD(), settings_file=cfg)
t5.restore_prefs()
assert t5.key_box.currentText() == "C", "a damaged settings file is ignored"
t5.shutdown()

# the sound library missing: the window opens, says why, and Start explains
class NoLib:
    pass
def boom_module():
    raise AU.AudioError("The sound system library (PortAudio) is not installed on this computer.")
t6 = AT.AutotuneTab(None, settings_file=os.path.join(UD, "x.json"))
t6.sound_module = boom_module
t6.refresh_devices()
assert "PortAudio" in t6.audio_problem and t6.problem_lbl.isVisibleTo(t6) and "PortAudio" in t6.problem_lbl.text()
MSGS.clear()
assert t6.start() is False and MSGS and "PortAudio" in MSGS[-1] and not t6.running()
t6.shutdown()
# no devices at all
class Empty(FakeSD):
    def query_devices(self, device=None, kind=None):
        return []
t7 = AT.AutotuneTab(None, sd=Empty(), settings_file=os.path.join(UD, "y.json"))
assert "No microphone" in t7.audio_problem
t7.shutdown()
# a card that refuses to open: the window explains and stays usable
t8 = AT.AutotuneTab(None, sd=Refusing(), settings_file=os.path.join(UD, "z.json"))
MSGS.clear()
assert t8.start() is False and "Device unavailable" in MSGS[-1] and t8.start_btn.isEnabled() and not t8.running()
t8.shutdown()

# the tuner drawing: levels and needle positions
assert AT.level_fraction(-120) == 0.0 and AT.level_fraction(0) == 1.0 and abs(AT.level_fraction(-30) - 0.5) < 1e-9
assert AT.TunerView.x_of(0, 0, 100) == 50 and AT.TunerView.x_of(-80, 0, 100) == 0 and AT.TunerView.x_of(80, 0, 100) == 100

# registered like the other add-ons
import addons
assert "autotune" in addons.shipped() and addons.info("autotune")["name"] == "Autotune"
spec = json.load(open(os.path.join(HERE, "addons_src", "autotune", "addon.json")))
assert spec["id"] == "autotune" and {r["import"] for r in spec["requires"]} == {"sounddevice", "cffi", "pycparser"}
assert spec["tabs"][0]["kind"] == "autotune" and spec["tabs"][0]["module"] == "autotune_tab"
print("PASS autotune tab")
