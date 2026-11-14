"""Autotune engine: notes and scales, the pitch measurement, and the whole engine on made-up voices (a pulse train through vowel resonators,
with vibrato, slides, breaths).  No sound card and no window are needed."""
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "addons_src", "autotune"))
import numpy as np
from scipy.signal import lfilter

import autotune_core as A

FS = 48000
RNG = np.random.default_rng(7)


def cents(f, ref):
    return 1200.0 * math.log2(f / ref)


def voice(f0, fs=FS, formants=((700, 80), (1200, 100), (2600, 150)), amp=0.5):
    """A vowel-like voice: a pulse at every period of the f0 track (Hz, one value per sample) through three resonators."""
    f0 = np.asarray(f0, float)
    ph = np.cumsum(f0) / fs
    pulses = np.zeros(len(f0))
    pulses[np.flatnonzero(np.diff(np.floor(ph)) > 0) + 1] = 1.0
    y = pulses
    for f, bw in formants:
        r = math.exp(-math.pi * bw / fs)
        th = 2 * math.pi * f / fs
        y = lfilter([1 - r], [1, -2 * r * math.cos(th), r * r], y)
    return (y / np.abs(y).max() * amp).astype(np.float32)


def measure(x, fs=FS, fmin=50.0, fmax=1000.0):
    """The pitch of a steady stretch, by a long autocorrelation: another method than the engine's own."""
    x = np.asarray(x, np.float64)
    x = x - x.mean()
    n = len(x)
    nf = 1 << (2 * n - 1).bit_length()
    X = np.fft.rfft(x, nf)
    r = np.fft.irfft(X * np.conj(X), nf)[:n]
    lo, hi = int(fs / fmax), int(fs / fmin)
    k = lo + int(np.argmax(r[lo:hi]))
    a, b, c = r[k - 1], r[k], r[k + 1]
    return fs / (k + 0.5 * (a - c) / (a - 2 * b + c))


def track(y, fs=FS, win=0.06, step=0.01, fmin=50.0):
    """(times, pitches) of a moving voice, a short window at a time (0.0 where there is none)."""
    w, s = int(win * fs), int(step * fs)
    ts, fs_out = [], []
    for i in range(0, len(y) - w, s):
        seg = y[i:i + w]
        if np.sqrt(np.mean(seg ** 2)) < 0.01:
            fs_out.append(0.0)
        else:
            fs_out.append(measure(seg, fs, fmin))
        ts.append((i + w / 2) / fs)
    return np.array(ts), np.array(fs_out)


def run(x, key="C", scale="Chromatic (every note)", speed=0.0, amount=1.0, fmin=100.0, block=256, custom=None):
    t = A.Autotuner(FS, fmin)
    t.allowed = A.allowed_notes(key, scale, custom)
    t.speed_ms, t.amount = speed, amount
    y = t.process_signal(x, block)
    return y, t


# ============================================================================================================ notes and scales
assert A.note_name(69) == "A4" and A.note_name(60) == "C4" and A.note_name(61) == "C#4" and A.note_name(21) == "A0"
assert abs(A.hz_to_midi(440.0) - 69) < 1e-12 and abs(A.midi_to_hz(60) - 261.6256) < 1e-3 and abs(A.hz_to_midi(432.0, 432.0) - 69) < 1e-12
al = A.allowed_notes("C", "Major")
assert [i for i in range(12) if al[i]] == [0, 2, 4, 5, 7, 9, 11]
al = A.allowed_notes("A", "Minor")
assert [i for i in range(12) if al[i]] == [0, 2, 4, 5, 7, 9, 11], "A minor has the notes of C major"
al = A.allowed_notes("D", "Major pentatonic")
assert [i for i in range(12) if al[i]] == [2, 4, 6, 9, 11]
assert A.allowed_notes("C", A.CUSTOM, [1, 0, 0, 0, 1])[:5] == (True, False, False, False, True) and len(A.allowed_notes("C", A.CUSTOM, [1])) == 12
assert all(len(A.allowed_notes("F#", s)) == 12 for s in A.SCALES)
chrom = A.allowed_notes("C", "Chromatic (every note)")
assert A.nearest_allowed(69.2, chrom) == 69 and A.nearest_allowed(69.6, chrom) == 70
cmaj = A.allowed_notes("C", "Major")
assert A.nearest_allowed(70.0, cmaj) in (69, 71) and A.nearest_allowed(69.4, cmaj) == 69 and A.nearest_allowed(66.6, cmaj) == 67
assert A.nearest_allowed(70.9, cmaj) == 71 and A.nearest_allowed(61.2, cmaj) == 62 and A.nearest_allowed(60.7, cmaj) == 60, "a note the scale does not have goes to the next one"
assert A.nearest_allowed(69.45, chrom, current=70) == 70 and A.nearest_allowed(69.45, chrom, current=70, stick=0.0) == 69 and A.nearest_allowed(69.3, chrom, current=70) == 69, "stickiness at the border"
assert A.nearest_allowed(60.2, chrom, current=70) == 60, "stickiness never holds a far note"
assert A.nearest_allowed(60.2, (False,) * 12) == 60, "no note ticked: the voice is left alone"

# ============================================================================================================ the pitch measurement
for f in (70.0, 110.0, 220.0, 440.0, 880.0):
    t = np.arange(FS // 2) / FS
    x = sum(np.sin(2 * np.pi * f * k * t) / k for k in (1, 2, 3, 4))
    hz, conf = A.yin(x[:2 * 800], FS, 60.0, 1000.0)
    assert abs(cents(hz, f)) < 3 and conf > 0.8, (f, hz, conf)
assert A.yin(np.zeros(1600), FS, 60, 1000) == (0.0, 0.0), "silence"
hz, conf = A.yin(RNG.standard_normal(1600) * 0.1, FS, 60, 1000)
assert hz == 0.0, "noise has no pitch"
x = voice(np.full(FS, 187.0))
hz, conf = A.yin(x[10000:10000 + 1920], FS, 100.0, 1000.0)
assert abs(cents(hz, 187.0)) < 2, hz

# ============================================================================================================ steady voices land on the note
for off in (-38, -20, 0, 25, 38):
    f_in = 220.0 * 2 ** (off / 1200)
    y, t = run(voice(np.full(2 * FS, f_in)))
    assert t.underruns == 0 and abs(cents(measure(y[int(0.8 * FS):int(1.8 * FS)]), 220.0)) < 0.5, (off, measure(y[int(0.8 * FS):int(1.8 * FS)]))
# a few pitches over the range, both ends
for f, fmin in ((105.0, 100.0), (130.0, 100.0), (330.0, 100.0), (600.0, 100.0), (65.0, 60.0), (160.0, 150.0), (900.0, 150.0)):
    f_in = f * 2 ** (-30 / 1200)
    y, t = run(voice(np.full(FS, f_in)), fmin=fmin)
    target = A.midi_to_hz(round(A.hz_to_midi(f_in)))
    assert t.underruns == 0 and abs(cents(measure(y[FS // 3:int(0.9 * FS)], fmin=fmin * 0.9), target)) < 3.0, (f, fmin)

# the key and the scale: 233 Hz (A#3) in C major has to go to A or B, in A# major it stays
f_in = A.midi_to_hz(58) * 2 ** (10 / 1200)
y, t = run(voice(np.full(FS, f_in)), key="A#", scale="Major")
assert abs(cents(measure(y[FS // 3:int(0.9 * FS)]), A.midi_to_hz(58))) < 1.0
y, t = run(voice(np.full(FS, f_in)), key="C", scale="Major")
m = measure(y[FS // 3:int(0.9 * FS)])
assert min(abs(cents(m, A.midi_to_hz(57))), abs(cents(m, A.midi_to_hz(59)))) < 1.0, m
# one note ticked: everything goes to it (C4 = 60), 300 cents away
y, t = run(voice(np.full(FS, A.midi_to_hz(62.9))), scale=A.CUSTOM, custom=[1])
assert abs(cents(measure(y[FS // 3:int(0.9 * FS)]), A.midi_to_hz(60))) < 1.0 or abs(cents(measure(y[FS // 3:int(0.9 * FS)]), A.midi_to_hz(72))) < 1.0

# ============================================================================================================ the same sound, whatever the blocks
x = voice(np.full(FS, 215.6))
ref = run(x, block=256)[0]
for blk in (64, 128, 480, 1000, 4096):
    y, t = run(x, block=blk)
    assert np.array_equal(y, ref), blk
    assert t.underruns == 0, (blk, t.underruns)

# ============================================================================================================ no voice: the sound goes through as it is
noise = (RNG.standard_normal(FS) * 0.1).astype(np.float32)
for blk in (64, 256, 1000):
    y, t = run(noise, block=blk)
    assert np.abs(y[3000:] - noise[3000:]).max() < 1e-5 and t.underruns == 0, blk
y, t = run(np.zeros(FS // 2, np.float32))
assert np.abs(y).max() == 0.0 and not t.state["voiced"], "silence stays silent"
y, t = run((np.sin(2 * np.pi * 220 * np.arange(FS // 4) / FS) * 3e-4).astype(np.float32))
assert not t.state["voiced"], "a very quiet sound is under the gate"

# ============================================================================================================ delay and level
t = A.Autotuner(FS, 100.0)
assert 20 < t.latency_ms() < 32, t.latency_ms()
assert A.Autotuner(FS, 150.0).latency < t.latency < A.Autotuner(FS, 60.0).latency, "a higher voice is a smaller delay"
x = voice(np.full(FS, 180.0))
y, t = run(x)
r_in = np.sqrt(np.mean(x[FS // 2:] ** 2))
r_out = np.sqrt(np.mean(y[FS // 2:] ** 2))
assert abs(20 * math.log10(r_out / r_in)) < 1.0, (r_in, r_out)          # about as loud as it went in
t = A.Autotuner(FS, 100.0)
for i in range(0, 20000, 500):
    t.process(x[i:i + 500])
assert -8 < t.state["in_db"] < -4 and t.state["out_db"] > -12, (t.state["in_db"], t.state["out_db"])          # the meters

# ============================================================================================================ the vowel stays the vowel
# 300 cents up, to the one note that is ticked: if the sound were just played faster, the resonance at 700 Hz would move to 832 Hz
def resonance(x, fs=FS):
    """The frequency of the strongest broad peak of the spectrum (smoothed over 150 Hz so that single harmonics do not count)."""
    seg = x[:len(x) // 4 * 4]
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    fr = np.fft.rfftfreq(len(seg), 1 / fs)
    k = max(3, int(150 / (fr[1] - fr[0])))
    sm = np.convolve(sp, np.ones(k) / k, "same")
    sel = (fr > 300) & (fr < 1800)
    return fr[sel][np.argmax(sm[sel])]
f_in = A.midi_to_hz(60 - 3)                  # A3
x = voice(np.full(2 * FS, f_in), formants=((700, 120), (1500, 200)))
y, t = run(x, scale=A.CUSTOM, custom=[1])    # only C
assert abs(cents(measure(y[FS // 2:int(1.5 * FS)]), A.midi_to_hz(60))) < 1.5
r_in, r_out = resonance(x[FS // 2:int(1.5 * FS)]), resonance(y[FS // 2:int(1.5 * FS)])
assert abs(r_out - r_in) / r_in < 0.06, (r_in, r_out)

# ============================================================================================================ vibrato and slides: the retune speed
n = 3 * FS
tt = np.arange(n) / FS
vib = 220.0 * 2 ** ((35 * np.sin(2 * np.pi * 5.5 * tt) + 20) / 1200)          # 5.5 Hz vibrato of +-35 cents, 20 cents sharp of A3
x = voice(vib)
y0, _ = run(x, speed=0.0)
ts, f = track(y0)
sel = (ts > 0.8) & (f > 0)
assert sel.sum() > 150 and np.abs([cents(v, 220.0) for v in f[sel]]).max() < 4.0, "speed 0: the vibrato is flattened onto the note"
y1, t1 = run(x, speed=250.0)
ts, f = track(y1)
sel = (ts > 1.2) & (f > 0)
c1 = np.array([cents(v, 220.0) for v in f[sel]])
assert c1.max() - c1.min() > 40, "a slow retune lets most of the vibrato through"
assert abs(c1.mean()) < 12, "but the pitch is still pulled to the note on average (it was +20 cents)"
y2, _ = run(x, speed=250.0, amount=0.0)
ts, f = track(y2)
c2 = np.array([cents(v, 220.0) for v in f[(ts > 1.2) & (f > 0)]])
assert abs(c2.mean() - 20) < 6 and c2.max() - c2.min() > 55, "amount 0: the voice as it was"
y3, _ = run(x, speed=0.0, amount=0.5)
ts, f = track(y3)
c3 = np.array([cents(v, 220.0) for v in f[(ts > 1.2) & (f > 0)]])
assert abs(c3.mean() - 10) < 6 and 25 < c3.max() - c3.min() < 55, "amount 0.5: half way"

# ============================================================================================================ a tune: notes with breaths and a consonant between them
notes = [(57, -25), (59, 30), (60, -10), (62, 35), (64, -40)]          # (MIDI note, how far off the singer is, in cents)
parts, expect = [], []
for m, off in notes:
    f = A.midi_to_hz(m) * 2 ** (off / 1200)
    parts.append(voice(np.full(int(0.5 * FS), f)))
    expect.append(A.midi_to_hz(m))
    parts.append((RNG.standard_normal(int(0.08 * FS)) * 0.05).astype(np.float32))      # a breath / "s"
x = np.concatenate(parts)
y, t = run(x, key="C", scale="Chromatic (every note)")
assert t.underruns == 0
pos = 0
for e in expect:
    seg = y[pos + int(0.18 * FS):pos + int(0.46 * FS)]
    assert abs(cents(measure(seg), e)) < 2.0, (e, measure(seg))
    pos += int(0.58 * FS)
# the breaths are not turned into notes: their sound is about the same loudness as it went in
pos = int(0.5 * FS)
for _ in notes:
    seg_in, seg_out = x[pos + 800:pos + 3000], y[pos + 800:pos + 3000]
    assert abs(20 * math.log10(np.sqrt(np.mean(seg_out ** 2)) / np.sqrt(np.mean(seg_in ** 2)))) < 3.0
    pos += int(0.58 * FS)

# a slide from A3 up to D4 with the key of C major: no gaps, no jumps in loudness
ramp = 220.0 * 2 ** (np.linspace(0, 500, 2 * FS) / 1200)
y, t = run(voice(ramp), key="C", scale="Major", speed=0.0)
env = np.sqrt(np.convolve(y ** 2, np.ones(480) / 480, "same"))[FS // 4:-FS // 4]
assert env.min() > 0.4 * env.max() and t.underruns == 0, (env.min(), env.max())
ts, f = track(y)
good = f[(ts > 0.3) & (ts < 1.7) & (f > 0)]
nn = np.array([A.hz_to_midi(v) for v in good])
steady = nn[1:-1][(np.abs(nn[1:-1] - nn[:-2]) < 0.05) & (np.abs(nn[1:-1] - nn[2:]) < 0.05)]       # (a window across a jump measures neither note)
assert len(steady) > 60 and np.abs(steady - np.round(steady)).max() < 0.12, "the slide goes in steps ..."
assert set(np.round(steady).astype(int) % 12) <= {0, 2, 4, 5, 7, 9, 11} and len(set(np.round(steady).astype(int))) >= 3, "... of the scale"

# ============================================================================================================ bypass, settings while running, short and long runs
t = A.Autotuner(FS, 100.0)
x = voice(np.full(FS, 205.0))
outs = [t.process(x[i:i + 256]) for i in range(0, 20 * 256, 256)]
t.bypass = True
outs.append(t.process(x[20 * 256:21 * 256]))
b = t.process(x[21 * 256:22 * 256])
assert np.array_equal(b, x[21 * 256:22 * 256]), "bypass: the sound as it comes in, with no delay"
t.bypass = False
for i in range(22, 40):
    o = t.process(x[i * 256:(i + 1) * 256])
assert len(o) == 256 and np.isfinite(o).all()
t.allowed = A.allowed_notes("C", "Major")
t.a4 = 432.0
t.speed_ms = 100.0
assert len(t.process(x[:100])) == 100 and len(t.process(x[:1])) == 1 and len(t.process(x[:0])) == 0, "odd block sizes"
t = A.Autotuner(FS, 100.0)
t0 = time.time()
long_x = voice(220.0 * 2 ** (30 * np.sin(2 * np.pi * 0.3 * np.arange(20 * FS) / FS) / 1200))
y = t.process_signal(long_x, 256)
took = time.time() - t0
assert t.underruns == 0 and len(y) == len(long_x) and np.isfinite(y).all()
assert took < 20.0 * 0.5, f"20 s of sound took {took:.1f} s: the engine has to run at least twice as fast as the sound"
assert len(t.inbuf) < 20000 and len(t.ybuf) < 30000 and len(t.entries) <= 600, "the buffers do not grow without end"
print("(20 s of sound in %.1f s, %.0f%% of real time)" % (took, 100 * took / 20))

# other sample rates
for fs2 in (16000, 22050, 44100, 96000):
    f_in = 200.0 * 2 ** (-25 / 1200)
    x = voice(np.full(fs2, f_in), fs=fs2)
    t = A.Autotuner(fs2, 100.0)
    y = t.process_signal(x, 256)
    assert t.underruns == 0 and abs(cents(measure(y[fs2 // 3:int(0.9 * fs2)], fs2), 200.0 * 2 ** (0 / 1200) * 0.9999 if False else A.midi_to_hz(round(A.hz_to_midi(f_in))))) < 2.0, fs2
print("PASS autotune core")
