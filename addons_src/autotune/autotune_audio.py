"""
autotune_audio.py - the sound-card side of the Autotune add-on: what sound systems and devices there are, and one stream that listens
and plays at the same time and hands every block of sound to an Autotuner (autotune_core.py).

The library that talks to the sound card is `sounddevice` (it brings its own PortAudio on Windows).  Everything here takes that module
as an argument, so the tests can give it a pretend sound card.
"""
import importlib
import sys
import threading

import numpy as np

import autotune_core as A

BLOCKS = (128, 256, 512, 1024)                 # the buffer sizes offered (samples); smaller is less delay and more risk of crackling
DEFAULT_BLOCK = 256
CHANNEL_CHOICES = (("Mix of all channels", None), ("Channel 1 only", 0), ("Channel 2 only", 1))


class AudioError(Exception):
    """Something about the sound card, in words for the person at the window."""


def load_sounddevice():
    """The sounddevice module, or an AudioError that says what to do."""
    try:
        return importlib.import_module("sounddevice")
    except ImportError as ex:
        raise AudioError("The sound library is missing. Open File > Add-ons and install the Autotune add-on again (it needs an internet "
                         "connection once).") from ex
    except OSError as ex:                        # PortAudio itself is not there
        if sys.platform.startswith("linux"):
            raise AudioError("The sound system library (PortAudio) is not installed on this computer. In a terminal: "
                             "sudo apt install libportaudio2") from ex
        raise AudioError(f"The sound system could not be loaded: {ex}") from ex


def _short_host(name):
    for key in ("WASAPI", "DirectSound", "MME", "WDM-KS", "ASIO", "Core Audio", "ALSA", "JACK", "OSS", "PulseAudio"):
        if key.lower() in name.lower():
            return key
    return name


def list_systems(sd):
    """The sound systems that have both a microphone and a place to play: [{'index', 'name', 'default'}], the best for low delay first
    (WASAPI on Windows), then the rest."""
    devs = sd.query_devices()
    out = []
    try:
        default_host = sd.default.hostapi
    except Exception:  # noqa: BLE001
        default_host = None
    for i, h in enumerate(sd.query_hostapis()):
        has_in = any(d["hostapi"] == i and d["max_input_channels"] > 0 for d in devs)
        has_out = any(d["hostapi"] == i and d["max_output_channels"] > 0 for d in devs)
        if has_in and has_out:
            out.append({"index": i, "name": h["name"], "default": i == default_host})
    out.sort(key=lambda s: (0 if "WASAPI" in s["name"] else 1 if s["default"] else 2, s["index"]))
    return out


def list_devices(sd, host_index, kind):
    """The devices of one sound system that listen (kind 'input') or play (kind 'output'): [{'index', 'name', 'channels', 'rate', 'default'}]."""
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    try:
        default = sd.query_hostapis(host_index)["default_" + kind + "_device"]
    except Exception:  # noqa: BLE001
        default = -1
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] == host_index and d[key] > 0:
            out.append({"index": i, "name": d["name"], "channels": int(d[key]), "rate": float(d["default_samplerate"]), "default": i == default})
    out.sort(key=lambda d: (0 if d["default"] else 1, d["index"]))
    return out


class Runner:
    """One open stream: listen, correct, play.  start() opens it, stop() closes it.  While it runs, `engine` is the Autotuner (change its
    settings freely), `dropouts` counts the times the sound card said it was starved or overfull, and `error` is set (to text) when the
    engine itself failed in the sound card's thread."""

    def __init__(self, sd):
        self.sd = sd
        self.stream = None
        self.engine = None
        self.dropouts = 0
        self.error = None
        self.blocks = 0
        self.in_channel = None
        self.info = {}
        self.lock = threading.Lock()

    def running(self):
        return self.stream is not None

    def start(self, in_dev, out_dev, block=DEFAULT_BLOCK, fmin=100.0, in_channel=None, host_name="", a4=440.0, configure=None):
        """in_dev / out_dev: entries of list_devices.  configure(engine) puts the window's settings into the new engine.  Returns a dict
        about what was opened; raises AudioError."""
        if self.stream is not None:
            self.stop()
        sd = self.sd
        cin = max(1, min(2, in_dev["channels"]))
        cout = max(1, min(2, out_dev["channels"]))
        fs, last = None, None
        for rate in dict.fromkeys(int(r) for r in (out_dev["rate"], in_dev["rate"], 48000, 44100)):
            try:
                sd.check_input_settings(device=in_dev["index"], channels=cin, dtype="float32", samplerate=rate)
                sd.check_output_settings(device=out_dev["index"], channels=cout, dtype="float32", samplerate=rate)
                fs = rate
                break
            except Exception as ex:  # noqa: BLE001 - PortAudioError and friends
                last = ex
        if fs is None:
            raise AudioError(f"These two devices do not agree on a sample rate ({last}). Choose another microphone or output, or another "
                             "sound system.")
        self.engine = A.Autotuner(fs, fmin, a4=a4)
        if configure:
            configure(self.engine)
        self.in_channel = in_channel if (in_channel is None or in_channel < cin) else 0
        self.dropouts, self.error, self.blocks = 0, None, 0
        extra = None
        if "wasapi" in host_name.lower() and hasattr(sd, "WasapiSettings"):
            try:
                w = sd.WasapiSettings(auto_convert=True)           # lets Windows convert the rate / channels instead of refusing
                extra = (w, w)
            except Exception:  # noqa: BLE001
                extra = None
        kw = dict(device=(in_dev["index"], out_dev["index"]), samplerate=fs, blocksize=int(block), dtype="float32", channels=(cin, cout),
                  latency="low", callback=self._callback)
        if extra:
            kw["extra_settings"] = extra
        try:
            stream = sd.Stream(**kw)
            stream.start()
        except Exception as ex:  # noqa: BLE001
            raise AudioError(f"The sound card would not open with these settings: {ex}\n\nTry a bigger buffer, another sound system "
                             "(for example WASAPI or MME) or another device.") from ex
        self.stream = stream
        dev_ms = 0.0
        try:
            lat = stream.latency
            dev_ms = 1000.0 * (sum(lat) if isinstance(lat, (tuple, list)) else float(lat))
        except Exception:  # noqa: BLE001
            dev_ms = 1000.0 * 2 * int(block) / fs
        self.info = {"fs": fs, "block": int(block), "engine_ms": self.engine.latency_ms(), "device_ms": dev_ms,
                     "total_ms": self.engine.latency_ms() + dev_ms, "channels": (cin, cout)}
        return dict(self.info)

    def stop(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass

    def _callback(self, indata, outdata, frames, time_info, status):
        """Runs in the sound card's thread: no waiting, no windows, nothing that can take long."""
        try:
            if status:
                self.dropouts += 1
            if self.in_channel is None or indata.shape[1] == 1:
                x = indata[:, 0] if indata.shape[1] == 1 else indata.mean(axis=1)
            else:
                x = indata[:, self.in_channel]
            y = self.engine.process(x)
            outdata[:] = y[:, None]
            self.blocks += 1
        except Exception as ex:  # noqa: BLE001 - never let an exception reach the sound card library
            outdata.fill(0)
            if self.error is None:
                self.error = f"{type(ex).__name__}: {ex}"
