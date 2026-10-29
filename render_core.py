"""
render_core.py - the renderer of the Render Studio (Mitsuba 3, a physically based path tracer).  No Qt, no CAD: it takes a scene description
and writes PNG files.  It can run in this process (render_cameras) or as a separate program:  python render_core.py scene.json out_folder
(the Render Studio uses the separate program, so a renderer problem can never close the modeller, and Cancel just stops it).

Scene description (a dict / JSON, lengths in mm, Z is up):
  bodies   [{"name", "mesh": path of a .npz (v: Nx3, n: Nx3, f: Mx3), "color": [r,g,b] 0..1, "roughness": 0..1, "metallic": 0..1}]
  cameras  [{"name", "origin": [x,y,z], "target": [x,y,z], "up": [x,y,z], "fov": vertical angle in degrees}]
  sun      {"on", "shadows", "date": "YYYY-MM-DD", "time": "HH:MM", "tz": hours from UTC, "lat", "lon", "north": degrees, "turbidity", "intensity"}
  ambient  0..1 (a plain white all-round light; useful when the sun is off)
  spot     {"on", "pos", "target", "power": 0..100, "cone": degrees, "color"}
  floor    {"on", "z", "color", "roughness"}   (a very large plane at height z)
  prefix   text put in front of every file name (optional)
  stop_file  path: when this file appears the render finishes the current pass, saves what it has and stops
  video    {"frames": [camera dicts], "fps", "file": "name.mp4"}  -> renders the frames and joins them into an MP4 (needs imageio-ffmpeg)
  render   {"denoise": true for the NVIDIA OptiX denoiser (graphics card), "fireflies": true to remove single bright pixels, "width", "height", "spp", "exposure": EV, "max_depth", "background": "sky" | "color" | "transparent", "bg_color": [r,g,b]}
"""
import datetime
import json
import math
import os
import sys

import numpy as np

# ---------------------------------------------------------------------------------------------- the sun
def sun_position(lat, lon, date, time, tz):
    """(elevation, azimuth) in degrees for a place (lat north +, lon east +), a local date 'YYYY-MM-DD', a local time 'HH:MM' and the offset of
    local time from UTC in hours.  Azimuth is measured from north, clockwise (east = 90).  NOAA's solar position formulas (good to ~0.1 deg)."""
    y, mo, d = (int(x) for x in date.split("-"))
    hh, mm = (int(x) for x in time.split(":")[:2])
    dt = datetime.datetime(y, mo, d, hh, mm)
    doy = dt.timetuple().tm_yday
    g = 2 * math.pi / 365.0 * (doy - 1 + (hh - 12) / 24.0)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = (hh * 60 + mm + eqt + 4 * lon - 60 * tz) % 1440                 # true solar time, minutes
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    cz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    zen = math.acos(max(-1.0, min(1.0, cz)))
    el = 90 - math.degrees(zen)
    sz = math.sin(zen)
    if sz < 1e-9:
        return el, 180.0
    ca = (math.sin(la) * cz - math.sin(decl)) / (math.cos(la) * sz)
    az = math.degrees(math.acos(max(-1.0, min(1.0, ca))))
    az = (180 - az) if ha < 0 else (180 + az)      # morning: sun in the east side (az < 180); afternoon: west
    return el, az % 360


def sun_vector(el, az, north=0.0):
    """Unit vector from the model towards the sun.  Model +Y points to north rotated clockwise (seen from above) by `north` degrees."""
    a = math.radians(az - north)
    e = math.radians(el)
    return np.array([math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e)])


# ---------------------------------------------------------------------------------------------- meshes
def write_ply(path, v, n, f):
    v, n, f = np.asarray(v, np.float32), np.asarray(n, np.float32), np.asarray(f, np.uint32)
    head = ("ply\nformat binary_little_endian 1.0\nelement vertex %d\nproperty float x\nproperty float y\nproperty float z\n"
            "property float nx\nproperty float ny\nproperty float nz\nelement face %d\nproperty list uchar uint vertex_indices\nend_header\n"
            % (len(v), len(f)))
    vd = np.concatenate([v, n], axis=1).astype("<f4")
    fd = np.zeros(len(f), dtype=[("c", "u1"), ("i", "<u4", 3)])
    fd["c"], fd["i"] = 3, f
    with open(path, "wb") as fh:
        fh.write(head.encode("ascii"))
        fh.write(vd.tobytes())
        fh.write(fd.tobytes())


def _bbox(sc):
    lo, hi = np.full(3, 1e30), np.full(3, -1e30)
    for b in sc["bodies"]:
        v = np.load(b["mesh"])["v"]
        lo, hi = np.minimum(lo, v.min(0)), np.maximum(hi, v.max(0))
    return lo, hi


# ---------------------------------------------------------------------------------------------- the scene
def _rgb(c):
    return {"type": "rgb", "value": [float(x) for x in c]}


def build(sc, cam, T, tmp):
    lo, hi = _bbox(sc)
    size = max(float(np.linalg.norm(hi - lo)), 1.0)
    cen = 0.5 * (lo + hi)
    r = sc["render"]
    d = {"type": "scene"}
    d["integrator"] = {"type": "path", "max_depth": int(r.get("max_depth", 8)), "hide_emitters": r.get("background", "sky") != "sky"}
    d["sensor"] = {"type": "perspective", "fov": float(cam["fov"]), "fov_axis": "y", "near_clip": 0.01 * size, "far_clip": 1000 * size,
                   "to_world": T().look_at(origin=list(map(float, cam["origin"])), target=list(map(float, cam["target"])),
                                           up=list(map(float, cam.get("up", [0, 0, 1])))),
                   "film": {"type": "hdrfilm", "width": int(r["width"]), "height": int(r["height"]), "pixel_format": "rgba", "rfilter": {"type": "gaussian"}},
                   "sampler": {"type": "independent", "sample_count": int(r["spp"])}}
    sun, info = sc.get("sun", {}), {}
    amb = float(sc.get("ambient", 0.0))
    if sun.get("on", True):
        el, az = sun_position(sun["lat"], sun["lon"], sun["date"], sun["time"], sun.get("tz", 0))
        info["sun_elevation"], info["sun_azimuth"] = el, az
        vec = sun_vector(max(el, 0.5), az, sun.get("north", 0.0))
        k = float(sun.get("intensity", 1.0))
        night = el <= 0
        d["sky"] = {"type": "sunsky", "sun_direction": [float(x) for x in vec], "turbidity": float(sun.get("turbidity", 3.0)),
                    "sun_scale": 0.0 if (not sun.get("shadows", True) or night) else k,
                    "sky_scale": k * (1.0 if sun.get("shadows", True) else 1.0 + 4.0 * math.sin(math.radians(max(el, 0.5))) ** 0.8)
                                 * (0.02 if night else 1.0)}
    if amb > 0:
        if "sky" in d:          # a scene may have only ONE environment emitter: the even light is added to the sky's brightness instead
            d["sky"]["sky_scale"] = float(d["sky"]["sky_scale"]) + 10.0 * amb
        else:
            d["ambient"] = {"type": "constant", "radiance": _rgb([amb] * 3)}
    sp = sc.get("spot", {})
    if sp.get("on"):
        pos, tgt = np.array(sp["pos"], float), np.array(sp["target"], float)
        dist = float(np.linalg.norm(tgt - pos)) or size
        col = np.array(sp.get("color", [1, 1, 1]), float)
        d["spot"] = {"type": "spot", "cutoff_angle": float(sp.get("cone", 30)), "beam_width": float(sp.get("cone", 30)) * 0.7,
                     "intensity": _rgb(col * float(sp.get("power", 50)) * 0.02 * dist * dist),
                     "to_world": T().look_at(origin=list(pos), target=list(tgt), up=[0, 0, 1])}
    fl = sc.get("floor", {})
    if fl.get("on"):
        half = 0.5 * float(fl.get("size", 400)) * size      # huge, so its edge is the horizon (below the horizon the sky is black)
        d["floor"] = {"type": "rectangle", "to_world": T().translate([float(cen[0]), float(cen[1]), float(fl["z"])]).scale([half, half, 1]),
                      "bsdf": {"type": "principled", "base_color": _rgb(fl.get("color", [0.55, 0.55, 0.55])), "roughness": float(fl.get("roughness", 0.8)),
                               "metallic": 0.0}}
    for i, b in enumerate(sc["bodies"]):
        z = np.load(b["mesh"])
        p = os.path.join(tmp, f"body{i}.ply")
        write_ply(p, z["v"], z["n"], z["f"])
        d[f"body{i}"] = {"type": "ply", "filename": p, "bsdf": {"type": "principled", "base_color": _rgb(b["color"]), "roughness": max(0.02, float(b["roughness"])),
                                                              "metallic": float(b["metallic"])}}
    return d, info


def render_hdr(sc, cam, tmp, mi, T, progress=None, stop=None):
    """Renders one camera in passes (so the progress is known, a Stop keeps the passes done so far, and a very high sample count does not
    need the memory of all samples at once).  Returns (rgb premultiplied by a, a, passes done, passes planned)."""
    import time
    d, info = build(sc, cam, T, tmp)
    scene = mi.load_dict(d)
    r = sc["render"]
    w, h, spp = int(r["width"]), int(r["height"]), int(r["spp"])
    per = int(max(1, min(32, (1 << 25) // max(1, w * h), spp)))        # samples per pass: at most ~33 million samples at a time
    n = (spp + per - 1) // per
    acc, done, t0 = None, 0, time.time()
    for k in range(n):
        img = np.array(mi.render(scene, spp=per, seed=k), dtype=np.float32)
        acc = img if acc is None else acc + img
        done += 1
        if progress:
            el = time.time() - t0
            progress(done / n, el / done * (n - done), el)
        if stop is not None and stop() and done < n:
            break
    return acc / done, done, n


def denoise(rgb, mi, say):
    """NVIDIA OptiX denoiser (graphics card only).  Returns the cleaned image, or the input if it cannot run."""
    try:
        h, w = rgb.shape[:2]
        den = mi.OptixDenoiser(input_size=[w, h], albedo=False, normals=False, temporal=False)
        out = den(mi.TensorXf(np.ascontiguousarray(rgb, dtype=np.float32)))
        out = np.array(out, dtype=np.float32).reshape(h, w, 3)
        if not np.all(np.isfinite(out)):
            raise ValueError("the denoiser returned bad numbers")
        return out
    except Exception as ex:
        say(f"(denoiser not used: {str(ex).splitlines()[0] if str(ex) else type(ex).__name__})")
        return rgb


def finish_image(sc, img, mi, say):
    """Linear rgba (rgb premultiplied by a) -> 8-bit sRGB array H x W x 3 (or 4 with transparency)."""
    rgb, a = img[..., :3], np.clip(img[..., 3:4], 0.0, 1.0)
    r = sc["render"]
    bg = r.get("background", "sky")
    if r.get("denoise"):
        rgb = denoise(rgb, mi, say)
    if r.get("fireflies", True):
        rgb = remove_fireflies(rgb)
    if bg != "sky":                                  # the sky is hidden from the camera (it still lights the scene): rgb is premultiplied by a
        rgb = np.where(a > 1e-3, rgb / np.maximum(a, 1e-3), 0.0)
    rgb = rgb * (2.0 ** float(r.get("exposure", 0.0)))
    if bg == "color":
        bgc = _srgb_to_lin(np.array(r.get("bg_color", [1, 1, 1]), float))
        rgb = a * rgb + (1.0 - a) * bgc
        a = None
    elif bg != "transparent":
        a = None
    out = _to_srgb8(rgb)
    if a is not None:
        out = np.concatenate([out, (a * 255 + 0.5).astype(np.uint8)], axis=2)
    return out


def remove_fireflies(rgb, k=4.0):
    """Single over-bright pixels (a path that happened to find a small bright light through a shiny surface) are pulled down to k times the
    median of their 3x3 neighbourhood.  Cheap, keeps edges and highlights that cover more than a pixel."""
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    p = np.pad(lum, 1, mode="edge")
    h, w = lum.shape
    stack = np.stack([p[i:i + h, j:j + w] for i in range(3) for j in range(3) if not (i == 1 and j == 1)], axis=0)
    med = np.median(stack, axis=0)
    lim = k * med + 0.05
    f = np.where(lum > lim, lim / np.maximum(lum, 1e-9), 1.0)
    return rgb * f[..., None]


def _srgb_to_lin(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _to_srgb8(lin):
    lin = np.clip(np.nan_to_num(lin), 0, None)
    lin = lin / (1.0 + 0.0 * lin)                    # plain clamp (no tone curve): white stays white, colours stay as set
    s = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(np.clip(lin, 1e-9, None), 1 / 2.4) - 0.055)
    return (np.clip(s, 0, 1) * 255 + 0.5).astype(np.uint8)


def _write_png(path, a):
    import zlib
    import struct
    h, w, c = a.shape
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))
    def chunk(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6 if c == 4 else 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


def load_mitsuba():
    import mitsuba as mi
    for v in ("cuda_ad_rgb", "llvm_ad_rgb", "scalar_rgb"):
        try:
            mi.set_variant(v)
            # a tiny test render proves the variant really works here (LLVM / CUDA libraries may be missing)
            from mitsuba import ScalarTransform4f as T
            s = mi.load_dict({"type": "scene", "integrator": {"type": "path"}, "sensor": {"type": "perspective", "film": {"type": "hdrfilm", "width": 8, "height": 8},
                              "sampler": {"type": "independent", "sample_count": 1}}, "s": {"type": "sphere"}})
            mi.render(s)
            return mi, v
        except Exception:
            continue
    raise RuntimeError("Mitsuba could not start in any mode")


def _fmt(sec):
    sec = int(max(0, sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _stopper(sc):
    f = sc.get("stop_file")
    return (lambda: bool(f) and os.path.exists(f)) if f else (lambda: False)


def render_cameras(sc, out_dir, names=None, say=print, tmp=None):
    """Renders the cameras of the scene (all, or those in `names`) to out_dir/<prefix><camera name>.png; returns the list of files.
    Prints lines 'PROGRESS <0..1> <seconds left>' for the window's progress bar."""
    import tempfile
    mi, variant = load_mitsuba()
    from mitsuba import ScalarTransform4f as T
    say(f"Renderer: Mitsuba {mi.__version__} ({variant})")
    tmp = tmp or tempfile.mkdtemp(prefix="gpd_render_")
    os.makedirs(out_dir, exist_ok=True)
    stop = _stopper(sc)
    files = []
    cams = [c for c in sc["cameras"] if names is None or c["name"] in names]
    for k, cam in enumerate(cams):
        safe = "".join(ch if ch.isalnum() or ch in " _-." else "_" for ch in cam["name"]).strip() or f"camera{k + 1}"
        path = os.path.join(out_dir, str(sc.get("prefix", "")) + safe + ".png")
        say(f"[{k + 1}/{len(cams)}] rendering {cam['name']} ({sc['render']['width']} x {sc['render']['height']}, {sc['render']['spp']} samples) ...")
        prog = lambda f, eta, el, k=k: say(f"PROGRESS {(k + f) / len(cams):.4f} {eta + (len(cams) - k - 1) * (el + eta):.0f}")
        img, done, n = render_hdr(sc, cam, tmp, mi, T, prog, stop)
        out = finish_image(sc, img, mi, say)
        _write_png(path, out)
        files.append(path)
        say(f"[{k + 1}/{len(cams)}] saved {path}" + (f"  (stopped early: {done} of {n} passes)" if done < n else ""))
        if stop():
            break
    return files


def frame_hash(sc):
    """Identifies the look of a video (everything but file locations), so frames left from a different setting are never reused."""
    import hashlib
    d = json.loads(json.dumps({k: v for k, v in sc.items() if k not in ("stop_file", "video", "prefix")}))
    h = hashlib.sha1()
    for b in d["bodies"]:
        h.update(str(os.path.getsize(b["mesh"])).encode())
        b["mesh"] = ""
    h.update(json.dumps(d, sort_keys=True).encode())
    h.update(json.dumps(sc["video"]["frames"], sort_keys=True).encode())
    return h.hexdigest()


def render_video(sc, out_dir, say=print, tmp=None):
    """Renders the frames of sc['video'] (a list of camera dicts, fps, file name) and joins them into an MP4 with ffmpeg.
    Frames already rendered with the SAME settings are kept (an interrupted video continues where it stopped); they are deleted when the
    MP4 is done."""
    import shutil
    import subprocess
    import tempfile
    mi, variant = load_mitsuba()
    from mitsuba import ScalarTransform4f as T
    say(f"Renderer: Mitsuba {mi.__version__} ({variant})")
    v = sc["video"]
    frames = v["frames"]
    n = len(frames)
    tmp = tmp or tempfile.mkdtemp(prefix="gpd_render_")
    os.makedirs(out_dir, exist_ok=True)
    fdir = os.path.join(out_dir, "_frames_" + os.path.splitext(os.path.basename(v["file"]))[0])
    os.makedirs(fdir, exist_ok=True)
    hf = os.path.join(fdir, "settings.hash")
    hx = frame_hash(sc)
    old = open(hf).read().strip() if os.path.exists(hf) else None
    if old != hx:
        for fn in os.listdir(fdir):
            if fn.endswith(".png"):
                os.remove(os.path.join(fdir, fn))
        with open(hf, "w") as fh:
            fh.write(hx)
    stop = _stopper(sc)
    import time
    t0, rendered = time.time(), 0
    for i, cam in enumerate(frames):
        path = os.path.join(fdir, f"frame_{i:05d}.png")
        if os.path.exists(path):
            continue
        say(f"frame {i + 1}/{n} ...")
        prog = lambda f, eta, el, i=i: say(f"PROGRESS {(i + f) / n:.4f} {eta + (el + eta) * (n - i - 1):.0f}")
        img, done, passes = render_hdr(sc, cam, tmp, mi, T, prog, stop)
        if done < passes:
            say("Stopped: the frames done so far are kept; render the video again to continue.")
            return None
        _write_png(path, finish_image(sc, img, mi, say)[..., :3])
        rendered += 1
        say(f"frame {i + 1}/{n} saved")
        if stop():
            say("Stopped: the frames done so far are kept; render the video again to continue.")
            return None
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    out = os.path.join(out_dir, v["file"])
    say("Joining the frames into the video ...")
    cmd = [exe, "-y", "-framerate", str(v["fps"]), "-i", os.path.join(fdir, "frame_%05d.png"), "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "14", "-preset", "slow", out]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        say("ffmpeg failed:\n" + res.stderr[-1500:])
        return None
    shutil.rmtree(fdir, ignore_errors=True)
    say(f"saved {out}")
    return out


if __name__ == "__main__":
    scene_path, out_dir = sys.argv[1], sys.argv[2]
    names = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    with open(scene_path, "r", encoding="utf-8") as fh:
        sc = json.load(fh)
    sys.stdout.reconfigure(line_buffering=True)
    say = lambda s: print(s, flush=True)
    if sc.get("video"):
        render_video(sc, out_dir, say=say)
    else:
        render_cameras(sc, out_dir, names, say=say)
    print("DONE", flush=True)
