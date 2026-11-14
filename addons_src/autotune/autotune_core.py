"""
autotune_core.py - the sound engine of the Autotune add-on.  It listens to a voice, works out which note of a key and scale the singer is
aiming at and moves the voice onto that note while the sound is still going.  Blocks of sound go in, the same number of blocks come out,
a fixed fraction of a second later (Autotuner.latency).  Only numpy is used: no sound card is needed to run or test it (the window,
autotune_tab.py, brings the sound card).

The sound goes through three steps:

  1. Pitch.  Every `hop` samples (about 3 ms) the pitch of the last stretch of sound is measured with the YIN method (a difference
     function, done with FFTs, whose first deep dip is one period of the voice).  A short vote over three measurements throws away
     single wrong ones, and a quiet or noisy stretch counts as "not voiced" (breath, "s", silence).
  2. The note.  The nearest note that the scale allows is the target; a small "stickiness" keeps a voice that hovers between two notes
     from flipping between them.  The correction is the distance to the target in cents.  "Retune speed" smooths that correction in
     time: at 0 it is applied at once (the hard, robotic effect), slower lets the singer's own vibrato and slides through.  "Amount"
     scales it.
  3. Moving the voice.  Time-domain PSOLA: the sound is cut into overlapping two-period grains, one per period of the voice, and the
     grains are laid down again one period of the wanted note apart.  Because the grains are cut out of the sound, not stretched, the
     vowel (the formants, the character of the voice) stays where it was and only the pitch moves.  Where nothing is voiced the sound is
     passed on untouched.

Everything is deterministic: the output does not depend on how the sound was cut into blocks.
"""
import math

import numpy as np

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
KEYS = NOTE_NAMES

# the scales, as the steps (in semitones) above the key note
SCALES = {
    "Chromatic (every note)": (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
    "Major": (0, 2, 4, 5, 7, 9, 11),
    "Minor": (0, 2, 3, 5, 7, 8, 10),
    "Harmonic minor": (0, 2, 3, 5, 7, 8, 11),
    "Major pentatonic": (0, 2, 4, 7, 9),
    "Minor pentatonic": (0, 3, 5, 7, 10),
    "Blues": (0, 3, 5, 6, 7, 10),
    "Dorian": (0, 2, 3, 5, 7, 9, 10),
    "Mixolydian": (0, 2, 4, 5, 7, 9, 10),
}
CUSTOM = "Only the notes I tick"

# how low a voice the engine listens for: it sets how long a stretch of sound the pitch is measured on, and with it the delay.
# (name -> lowest pitch in Hz)
VOICES = {"Low voice (down to about B1)": 60.0, "Normal voice (down to about G2)": 100.0, "High voice (down to about D3)": 150.0}
DEFAULT_VOICE = "Normal voice (down to about G2)"


def hz_to_midi(f, a4=440.0):
    return 69.0 + 12.0 * math.log2(f / a4)


def midi_to_hz(m, a4=440.0):
    return a4 * 2.0 ** ((m - 69.0) / 12.0)


def note_name(midi):
    """'A4' for MIDI note 69."""
    m = int(round(midi))
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


def allowed_notes(key, scale, custom=None):
    """The twelve flags (index 0 = C) of the notes a key and scale allow.  scale == CUSTOM: `custom` is the twelve flags itself."""
    if scale == CUSTOM:
        flags = [bool(v) for v in (custom or [])][:12]
        flags += [False] * (12 - len(flags))
        return tuple(flags)
    k = KEYS.index(key) if isinstance(key, str) else int(key) % 12
    flags = [False] * 12
    for s in SCALES[scale]:
        flags[(k + s) % 12] = True
    return tuple(flags)


def nearest_allowed(m, allowed, current=None, stick=0.15):
    """The note (an integer MIDI number) of `allowed` that is nearest to m (a MIDI pitch with decimals).  `current` is the note chosen
    last time: it is kept until another note is nearer by more than `stick` semitones, so a voice on the border does not flip."""
    if not any(allowed):
        return int(round(m))
    lo = int(math.floor(m)) - 7
    best, best_d = None, 1e9
    for n in range(lo, lo + 16):
        if allowed[n % 12]:
            d = abs(n - m)
            if d < best_d:
                best, best_d = n, d
    if current is not None and allowed[current % 12] and abs(current - m) <= best_d + stick:
        return current
    return best


# ============================================================================================================ pitch (YIN)
_FFT_SIZES = {}


def _fft_size(n):
    s = _FFT_SIZES.get(n)
    if s is None:
        s = 1 << (max(n, 2) - 1).bit_length()
        _FFT_SIZES[n] = s
    return s


def yin(frame, fs, fmin, fmax, threshold=0.15):
    """The pitch of `frame` (a stretch of mono sound at least 2 periods of fmin long): (frequency in Hz or 0.0 when there is none,
    confidence 0..1).  The method of de Cheveigne and Kawahara (2002): the cumulative-mean-normalised difference function, the first dip
    below `threshold`, refined to a fraction of a sample."""
    x = np.asarray(frame, np.float64)
    n = len(x)
    tau_max = int(fs / fmin)
    tau_min = max(2, int(fs / fmax))
    w = n - tau_max
    if w < tau_max // 2 or tau_min >= tau_max:
        return 0.0, 0.0
    c = np.concatenate(([0.0], np.cumsum(x * x)))
    e0 = c[w] - c[0]
    if e0 <= 1e-12:
        return 0.0, 0.0
    taus = np.arange(tau_max + 1)
    et = c[w + taus] - c[taus]
    nfft = _fft_size(n + w)
    r = np.fft.irfft(np.fft.rfft(x, nfft) * np.conj(np.fft.rfft(x[:w], nfft)), nfft)[:tau_max + 1]
    d = np.maximum(e0 + et - 2.0 * r, 0.0)
    d[0] = 0.0
    cs = np.cumsum(d[1:])
    cmnd = np.ones(tau_max + 1)
    cmnd[1:] = d[1:] * taus[1:] / np.maximum(cs, 1e-12)
    below = np.flatnonzero(cmnd[tau_min:tau_max + 1] < threshold)
    if len(below) == 0:
        return 0.0, max(0.0, 1.0 - float(cmnd[tau_min:tau_max + 1].min()))
    t = tau_min + int(below[0])
    while t + 1 <= tau_max and cmnd[t + 1] < cmnd[t]:
        t += 1
    tf = float(t)
    if 1 <= t < tau_max:
        a, b, cc = cmnd[t - 1], cmnd[t], cmnd[t + 1]
        den = a - 2.0 * b + cc
        if den > 1e-12:
            tf = t + 0.5 * (a - cc) / den
    return fs / tf, 1.0 - float(cmnd[t])


# ============================================================================================================ the engine
class Autotuner:
    """Live pitch correction.  process(block) takes mono float32 sound of any length and returns as many samples, `latency` samples late.

    Settings (change them whenever, also while sound is going through): allowed (12 flags, see allowed_notes), speed_ms, amount, bypass, a4.
    What it is doing (read it whenever): state (a dict, replaced about every 3 ms), underruns, and the counters of the meters."""

    def __init__(self, fs=48000, fmin=100.0, fmax=1000.0, a4=440.0):
        self.fs = int(fs)
        self.fmin = float(fmin)
        self.fmax = float(min(fmax, fs / 6.0))
        self.a4 = float(a4)
        # settings
        self.allowed = allowed_notes("C", "Chromatic (every note)")
        self.speed_ms = 20.0
        self.amount = 1.0
        self.bypass = False
        self.threshold = 0.15            # YIN: lower is stricter about what counts as a clear pitch
        self.gate_db = -50.0             # quieter than this is not a voice
        self.stick = 0.15                # semitones
        # sizes
        self.hop = max(32, int(round(self.fs * 0.0027)))
        self.tau_max = int(self.fs / self.fmin)
        self.frame = 2 * self.tau_max
        self.latency = int(math.ceil(2.2 * self.tau_max)) + 2 * self.hop
        self.t_first = self.frame - self.frame // 4         # time the first pitch entry belongs to (the entries are `hop` apart)
        self.unvoiced_T = max(16, int(round(self.fs * 0.005)))
        self.reset()

    # ---------------------------------------------------------------------------------------------------- state
    def reset(self):
        pad = self.latency + 2 * self.tau_max
        self.n_in = 0
        self.in0 = -pad
        self.inbuf = np.zeros(pad, np.float32)
        self.det_k = 0                                   # the next pitch frame ends at frame + det_k * hop
        self.entries = []                                # per hop: (f0 or 0.0 if not voiced, cents applied, period in samples)
        self.entry0 = 0                                  # number of the first entry kept
        self.raw = []                                    # last raw f0's (0.0 = none)
        self.cur_note = None
        self.c_applied = 0.0
        self.was_voiced = False
        self.ts = 0.0                                    # where the next grain is centred (output time)
        self.ta = None                                   # where the last grain was cut from (input time); None = not following a voice
        self.y0 = -pad
        self.ybuf = np.zeros(pad, np.float64)
        self.wbuf = np.zeros(pad, np.float64)
        self.out_pos = -self.latency
        self.final = -self.latency
        self.underruns = 0
        self.state = {"voiced": False, "hz": 0.0, "note": "", "cents": 0.0, "target_hz": 0.0, "applied": 0.0, "in_db": -120.0, "out_db": -120.0}
        self._wins = {}
        self._byp = bool(self.bypass)
        self.in_db, self.out_db = -120.0, -120.0

    def latency_ms(self):
        return 1000.0 * self.latency / self.fs

    # ---------------------------------------------------------------------------------------------------- the blocks
    def process(self, x):
        x = np.ascontiguousarray(np.asarray(x, np.float32).reshape(-1))
        n = len(x)
        if n == 0:
            return x.copy()
        self.in_db = _db(float(np.abs(x).max()))
        self.inbuf = np.concatenate((self.inbuf, x))
        self.n_in += n
        self._detect()
        self._synth()
        wet = self._emit(n)
        byp = bool(self.bypass)
        if byp or self._byp:                             # dry <-> wet: a short ramp, so switching does not click
            m = np.linspace(1.0 if self._byp else 0.0, 1.0 if byp else 0.0, n, dtype=np.float32)
            out = x * m + wet * (1.0 - m)
        else:
            out = wet
        self._byp = byp
        self.out_db = _db(float(np.abs(out).max()))
        self.state["in_db"], self.state["out_db"] = self.in_db, self.out_db
        self._trim()
        return np.clip(out, -1.0, 1.0)

    def process_signal(self, x, block=256):
        """All of `x` through the engine (a fresh start), cut into blocks, with the delay taken out: as many samples as x, in time with it."""
        self.reset()
        x = np.asarray(x, np.float32).reshape(-1)
        n = len(x)
        z = np.concatenate((x, np.zeros(self.latency + block, np.float32)))
        out = [self.process(z[i:i + block]) for i in range(0, len(z) - len(z) % block, block)]
        return np.concatenate(out)[self.latency:self.latency + n]

    # ---------------------------------------------------------------------------------------------------- 1. pitch and 2. the note
    def _detect(self):
        while self.frame + self.det_k * self.hop <= self.n_in:
            end = self.frame + self.det_k * self.hop
            fr = self.inbuf[end - self.frame - self.in0:end - self.in0].astype(np.float64)
            rms_db = _db(float(np.sqrt(np.mean(fr * fr))))
            f0, _conf = yin(fr, self.fs, self.fmin, self.fmax, self.threshold) if rms_db > self.gate_db else (0.0, 0.0)
            self.det_k += 1
            self._control(f0)

    def _control(self, f0):
        """One pitch measurement in: the vote, the note, the smoothed correction; one entry out."""
        self.raw = (self.raw + [f0])[-3:]
        found = sorted(v for v in self.raw if v > 0.0)
        voiced = len(found) >= 2 or (len(found) == 1 and f0 > 0.0 and not self.was_voiced and len(self.raw) == 1)
        if not voiced:
            self.entries.append((0.0, self.c_applied, float(self.unvoiced_T)))
            self.was_voiced = False
            self.cur_note = None
            self.state.update(voiced=False, hz=0.0, note="", cents=0.0, target_hz=0.0, applied=0.0)
            return
        hz = found[len(found) // 2]
        m = hz_to_midi(hz, self.a4)
        target = nearest_allowed(m, self.allowed, self.cur_note, self.stick)
        self.cur_note = target
        c_target = (target - m) * 100.0
        if not self.was_voiced or self.speed_ms <= 0.0:
            self.c_applied = c_target
        else:
            a = 1.0 - math.exp(-(self.hop / self.fs) / (self.speed_ms / 1000.0))
            self.c_applied += a * (c_target - self.c_applied)
        self.was_voiced = True
        c_out = self.c_applied * float(min(1.0, max(0.0, self.amount)))
        self.entries.append((hz, c_out, self.fs / hz))
        self.state.update(voiced=True, hz=hz, note=note_name(target), cents=-c_target, target_hz=midi_to_hz(target, self.a4), applied=c_out)

    def _entry_at(self, t):
        k = int(round((t - self.t_first) / self.hop))
        k = max(k, 0)
        i = k - self.entry0
        if i >= len(self.entries):
            return None
        return self.entries[max(i, 0)]

    # ---------------------------------------------------------------------------------------------------- 3. moving the voice (TD-PSOLA)
    def _win(self, ti):
        w = self._wins.get(ti)
        if w is None:
            w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(2 * ti) / (2.0 * ti))
            self._wins[ti] = w
        return w

    def _refine(self, ta, T):
        """The centre of the next period after `ta`: about ta + T, moved by up to T/8 to where the sound looks most like the last period."""
        ti = int(round(T))
        hw = max(2, ti // 2)
        dmax = max(1, ti // 8)
        cand = ta + ti
        lo, hi = cand - dmax - hw, cand + dmax + hw
        if hi > self.n_in:
            return None
        ref = self.inbuf[ta - hw - self.in0:ta + hw - self.in0].astype(np.float64)
        big = self.inbuf[lo - self.in0:hi - self.in0].astype(np.float64)
        if len(ref) != 2 * hw or len(big) != 2 * hw + 2 * dmax:
            return cand
        dots = np.correlate(big, ref, "valid")
        c = np.concatenate(([0.0], np.cumsum(big * big)))
        en = c[2 * hw:2 * hw + len(dots)] - c[:len(dots)]
        score = dots / np.sqrt(np.maximum(en, 1e-12))
        return cand - dmax + int(np.argmax(score))

    def _ensure(self, hi):
        have = self.y0 + len(self.ybuf)
        if hi > have:
            add = hi - have + 4096
            self.ybuf = np.concatenate((self.ybuf, np.zeros(add)))
            self.wbuf = np.concatenate((self.wbuf, np.zeros(add)))

    def _synth(self):
        need = self.n_in - self.latency          # everything before this must be final
        while True:
            e = self._entry_at(self.ts)
            if e is None:
                self.final = int(self.ts) - self.tau_max
                return
            hz, c, T = e
            voiced = hz > 0.0
            ti = int(round(T))
            guard = max(ti, self.unvoiced_T)              # the next grain may be longer than this one (voice -> breath): leave room for it
            if int(self.ts) - guard >= need:
                self.final = max(need, int(self.ts) - guard)
                return
            ts_i = int(round(self.ts))
            if not voiced or self.ta is None or abs(self.ta - ts_i) > 3 * ti:
                ta = ts_i
            else:
                ta = self.ta
                while ta + T <= self.ts:
                    ta = self._refine(ta, T)
                    if ta is None:
                        break
                if ta is None:
                    self.final = int(self.ts) - guard
                    return
            if ta + ti + 1 > self.n_in:
                self.final = int(self.ts) - guard
                return
            ti = max(2, min(ti, ts_i - self.out_pos))      # never reach back into sound that has been played already (a safety net)
            win = self._win(ti)
            seg = self.inbuf[ta - ti - self.in0:ta + ti - self.in0]
            self._ensure(ts_i + ti + 1)
            a0 = ts_i - ti - self.y0
            self.ybuf[a0:a0 + 2 * ti] += seg * win
            self.wbuf[a0:a0 + 2 * ti] += win
            self.ta = ta if voiced else None
            alpha = 2.0 ** (c / 1200.0) if voiced else 1.0
            self.ts += T / alpha

    def _emit(self, n):
        a, b = self.out_pos, self.out_pos + n
        if b > self.final and b > 0:                     # (before time 0 there is nothing to be late with)
            self.underruns += 1
        self._ensure(b)
        i = a - self.y0
        y, w = self.ybuf[i:i + n], self.wbuf[i:i + n]
        out = (y / np.maximum(w, 0.25)).astype(np.float32)
        self.out_pos = b
        return out

    def _trim(self):
        keep_in = self.latency + 4 * self.tau_max + 4 * self.hop
        drop = len(self.inbuf) - keep_in
        if drop > 0:
            self.inbuf = self.inbuf[drop:]
            self.in0 += drop
        drop = self.out_pos - self.y0
        if drop > 0:
            self.ybuf = self.ybuf[drop:]
            self.wbuf = self.wbuf[drop:]
            self.y0 += drop
        if len(self.entries) > 600:
            cut = len(self.entries) - 300
            del self.entries[:cut]
            self.entry0 += cut


def _db(v):
    return 20.0 * math.log10(v) if v > 1e-6 else -120.0
