"""pe_speech.py - reading a document aloud, sentence by sentence, with the Windows voices (SAPI), without blocking the window (no Qt here).

Speaker       one worker thread that speaks the sentences from a starting sentence to the end and reports through a queue:
                  ("sentence", run, i)  the voice is about to say sentence i
                  ("done", run, natural) the thread ended (natural: it reached the end, nobody stopped it)
                  ("error", run, text)  something went wrong
              Pause and resume are exact: the voice itself is paused, so it goes on in the middle of the sentence.  Stop ends the thread.
Hub           the one voice of the editor: whichever PDF starts reading stops the one that was reading.  It numbers the runs, so that what a
              stopped run still puts in the queue is thrown away.
SapiBackend   the real voices (pywin32 - downloaded the first time, see pe_deps).  A test passes a backend of its own (list_voices(), engine()).
"""
import queue
import threading

import pe_deps

SVS_ASYNC = 1
SVS_PURGE = 2
SVS_NOT_XML = 16
RATE_MIN, RATE_MAX = -5, 10                    # the speed slider (SAPI itself takes -10..10)


class SapiBackend:
    """The Windows voices through pywin32."""

    def available(self):
        return pe_deps.voice_ready()

    def list_voices(self):
        """The names of the installed voices ([] when speech is not available).  Asked in a thread of its own: COM wants to be started in every thread."""
        result = []

        def probe():
            mods = pe_deps.load_sapi()
            if mods is None:
                return
            pc, wc = mods
            pc.CoInitialize()
            try:
                v = wc.Dispatch("SAPI.SpVoice")
                vs = v.GetVoices()
                for i in range(vs.Count):
                    result.append(vs.Item(i).GetDescription())
                del vs, v
            except Exception:                  # noqa: BLE001
                pass
            finally:
                pc.CoUninitialize()
        t = threading.Thread(target=probe, daemon=True)
        t.start()
        t.join(5)
        return result

    def engine(self):
        """Called in the speaking thread."""
        mods = pe_deps.load_sapi()
        if mods is None:
            raise RuntimeError("Speech needs Windows and its voice support (it is downloaded the first time you press Play).")
        return SapiEngine(*mods)


class SapiEngine:
    def __init__(self, pc, wc):
        self.pc = pc
        pc.CoInitialize()
        try:
            self.voice = wc.Dispatch("SAPI.SpVoice")
            self.vs = self.voice.GetVoices()
        except BaseException:
            pc.CoUninitialize()
            raise
        self.last_voice = None

    def apply(self, voice_name, rate, volume):
        self.voice.Rate = int(rate)
        self.voice.Volume = int(volume)
        if voice_name != self.last_voice:
            for i in range(self.vs.Count):
                if self.vs.Item(i).GetDescription() == voice_name:
                    self.voice.Voice = self.vs.Item(i)
                    break
            self.last_voice = voice_name

    def speak(self, text):
        self.voice.Speak(text, SVS_ASYNC | SVS_NOT_XML)

    def purge(self):
        self.voice.Speak("", SVS_ASYNC | SVS_PURGE)

    def pause(self):
        self.voice.Pause()

    def resume(self):
        self.voice.Resume()

    def wait(self, ms):
        """True when the sentence has been said."""
        return bool(self.voice.WaitUntilDone(ms))

    def close(self):
        try:
            del self.vs, self.voice
        finally:
            self.pc.CoUninitialize()


class Speaker:
    def __init__(self, events, backend=None):
        self.events = events                   # a queue.Queue of tuples
        self.backend = backend or SapiBackend()
        self.rate = 1
        self.voice_name = None
        self.volume = 100
        self._thread = None
        self._stop = threading.Event()
        self._pause = threading.Event()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def paused(self):
        return self.running and self._pause.is_set()

    def start(self, tag, texts, first):
        self.stop()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(tag, texts, first, self._stop, self._pause), daemon=True)
        self._thread.start()

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    def stop(self):
        if self._thread is not None:
            self._stop.set()
            self._thread.join(2)
        self._thread = None

    def _run(self, tag, texts, first, stop, pause):
        natural = False
        eng = None
        try:
            eng = self.backend.engine()
            i = first
            while i < len(texts) and not stop.is_set():
                text = texts[i].strip()
                if not text:
                    i += 1
                    continue
                eng.apply(self.voice_name, self.rate, self.volume)
                self.events.put(("sentence", tag, i))
                eng.speak(text)
                paused = False
                while True:
                    if stop.is_set():
                        eng.purge()
                        break
                    if pause.is_set() and not paused:
                        eng.pause()
                        paused = True
                    elif paused and not pause.is_set():
                        eng.resume()
                        paused = False
                    if eng.wait(60):
                        break
                i += 1
            natural = not stop.is_set()
        except Exception as e:                 # noqa: BLE001 - whatever went wrong is shown to the person, never raised in a thread
            self.events.put(("error", tag, str(e)))
        finally:
            if eng is not None:
                try:
                    eng.close()
                except Exception:              # noqa: BLE001
                    pass
            self.events.put(("done", tag, natural))


class Hub:
    """The one voice of the editor tab, shared by every PDF in it."""

    def __init__(self, backend=None):
        self.events = queue.Queue()
        self.speaker = Speaker(self.events, backend)
        self.run_id = 0
        self.owner = None                      # the reader that is reading (or is paused)
        self._voices = None

    # -- settings
    def voices(self):
        if self._voices is None:
            self._voices = self.speaker.backend.list_voices()
        return self._voices

    def forget_voices(self):
        self._voices = None

    @property
    def rate(self):
        return self.speaker.rate

    @rate.setter
    def rate(self, v):
        self.speaker.rate = max(RATE_MIN, min(RATE_MAX, int(round(float(v)))))

    @property
    def voice_name(self):
        return self.speaker.voice_name

    @voice_name.setter
    def voice_name(self, v):
        self.speaker.voice_name = v

    # -- reading
    @property
    def running(self):
        return self.speaker.running

    @property
    def paused(self):
        return self.speaker.paused

    def reading(self, owner):
        """True while `owner` is reading or paused."""
        return self.owner is owner and self.running

    def start(self, owner, texts, first):
        self.speaker.stop()
        self.drain()
        self.run_id += 1
        self.owner = owner
        self.speaker.start(self.run_id, texts, first)

    def stop(self):
        self.speaker.stop()
        self.drain()
        self.owner = None

    def pause(self):
        self.speaker.pause()

    def resume(self):
        self.speaker.resume()

    def drain(self):
        try:
            while True:
                self.events.get_nowait()
        except queue.Empty:
            pass

    def poll(self):
        """What the current run has reported since the last call: [(kind, value)] ("sentence", i) / ("done", natural) / ("error", text)."""
        out = []
        try:
            while True:
                kind, tag, val = self.events.get_nowait()
                if tag == self.run_id:
                    out.append((kind, val))
        except queue.Empty:
            pass
        return out
