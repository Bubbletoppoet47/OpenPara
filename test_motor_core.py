"""Motor Control: error words, simulated board (calibration, closed loop, Hall limits), analysis, settings backup. No hardware, no GUI."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "addons_src", "motor"))
import motor_model as M, motor_link as L, motor_analysis as A

# ---- error words
assert M.error_report(0, 0, 0, 0) == []
r = M.error_report(0x100, 0, 0x10, 0)
assert any("Sensor failed" in x for x in r) and any("Hall" in x for x in r), r
assert "0x8000" in " ".join(M.decode(0x8000, M.AXIS_ERRORS, "Axis")), "unknown bits are shown, not hidden"
assert M.suggested_cpr(1, 7) == 42 and M.suggested_cpr(0, 7) is None
assert all(f.path for f in M.ALL_FIELDS) and len({f.path for f in M.ALL_FIELDS}) == len(M.ALL_FIELDS)

# ---- Hall facts
f = A.hall_facts(7, 2.0)
assert f["steps_per_turn"] == 42 and abs(f["degrees_per_step"] - 360 / 42) < 1e-9 and abs(f["step_rate_hz"] - 84) < 1e-9
assert abs(A.lowest_usable_speed(7, 100) - 100 / 42) < 1e-9

# ---- simulated board: refuses closed loop before calibration
s = L.SimLink()
assert s.info()["fw_version_minor"] == 5 and s.get("axis0.nothing.here") is None
s.set("axis0.requested_state", M.CLOSED_LOOP); s.advance(0.1)
assert s.get("axis0.error") & 1 and s.state == M.IDLE, "not calibrated -> invalid state"
assert "Invalid state" in " ".join(M.error_report(s.get("axis0.error"), 0, 0, 0))
s.clear_errors()

# ---- Hall calibration with a wrong cpr fails with the right sensor error; with the right one it works
s.set("axis0.encoder.config.mode", 1); s.set("axis0.encoder.config.cpr", 40)
s.set("axis0.requested_state", M.FULL_CAL); s.advance(12)
assert s.get("axis0.encoder.error") & 2 and s.state == M.IDLE and not s.get("axis0.encoder.is_ready")
s.clear_errors(); s.set("axis0.encoder.config.cpr", 42)
s.set("axis0.requested_state", M.FULL_CAL); s.advance(12)
assert s.state == M.IDLE and not s.get("axis0.error") and s.get("axis0.motor.is_calibrated") and s.get("axis0.encoder.is_ready")
res = {k: s.get(v) for k, v in M.CAL_RESULT.items()}
chk = M.check_calibration(res)
assert chk[0][0] == "ok" and abs(res["R"] - 0.12) < 1e-9, chk
assert M.check_calibration({"R": 0.0, "L": 0.0})[0][0] == "bad"

# ---- speed control: Hall at a high filter bandwidth is rougher than at a low one, an encoder is smoothest
def run(mode, cpr, bw, speed=3.0):
    b = L.SimLink(); b.set("axis0.encoder.config.mode", mode); b.set("axis0.encoder.config.cpr", cpr); b.set("axis0.encoder.config.bandwidth", bw)
    b.set("axis0.requested_state", M.FULL_CAL); b.advance(12)
    b.set("axis0.controller.config.control_mode", 2); b.set("axis0.controller.input_vel", speed); b.set("axis0.requested_state", M.CLOSED_LOOP)
    b.advance(1.5); ts, vs = [], []
    for _ in range(300):
        b.advance(0.01); ts.append(b.now()); vs.append(b.get("axis0.encoder.vel_estimate"))
    assert b.state == M.CLOSED_LOOP and not b.get("axis0.error"), b.err
    return abs(b.omega - speed) < 0.3, A.ripple(vs)[2], ts, vs
ok1, rip_hall_hi, ts, vs = run(1, 42, 1000.0)
ok2, rip_hall_lo, *_ = run(1, 42, 100.0)
ok3, rip_enc, *_ = run(0, 4000, 1000.0)
assert ok2 and ok3, "the motor reaches the speed (the estimate may be rough, the motor is not)"
assert rip_hall_hi > rip_hall_lo > 0 and rip_enc < rip_hall_hi, (rip_hall_hi, rip_hall_lo, rip_enc)
v = A.hall_verdict(7, 3.0, ts, vs)
assert v and v[0][0] in ("ok", "warn", "bad") and "ripple" in v[0][1].lower()

# ---- speed limit stops runaway; undervoltage stops the board
b = L.SimLink(vbus=5.0); b.set("axis0.requested_state", M.FULL_CAL); b.advance(1)
assert b.get("axis0.error") & 2 or b.state == M.IDLE
b = L.SimLink(); b.set("axis0.requested_state", M.FULL_CAL); b.advance(12)
b.set("axis0.controller.config.control_mode", 2); b.set("axis0.controller.config.vel_limit", 1.0); b.set("axis0.controller.input_vel", 0.5); b.set("axis0.requested_state", M.CLOSED_LOOP)
b.advance(1); assert b.state == M.CLOSED_LOOP, "the board holds the limit by itself"
b.disturb = -2.0     # something drags the shaft along
b.advance(5)
assert b.state == M.IDLE and (b.get("axis0.controller.error") & 1), "over speed -> idle"

# ---- settings backup and restore
b = L.SimLink(); b.set("axis0.motor.config.current_lim", 4.5)
text = A.backup_text(b)
b.set("axis0.motor.config.current_lim", 20.0)
assert A.restore(text, b) == 1 and b.get("axis0.motor.config.current_lim") == 4.5
try:
    A.restore("{}", b); raise SystemExit("FAIL wrong file accepted")
except ValueError:
    pass
b.save(); b.set("axis0.motor.config.current_lim", 1.0); b.reboot(); assert b.get("axis0.motor.config.current_lim") == 4.5
b.erase(); assert b.get("axis0.motor.config.current_lim") == 10.0
# ---- checks before calibration
w = A.check_settings({M.a("encoder.config.mode"): 1, M.a("encoder.config.cpr"): 40, M.a("motor.config.pole_pairs"): 7, M.a("motor.config.current_lim"): 50})
assert [l for l, _ in w].count("bad") == 1 and any("high" in t for _, t in w)
# ---- development-build firmware label, Hall wiring verdicts, new fields
assert "development build" in M.fw_label(L.SimLink(dev_build=True).info()) and M.fw_label(L.SimLink().info()) == "firmware 0.5.4"
assert A.hall_wiring([7, 7, 7])[1][0][0] == "bad" and not A.hall_wiring([7])[0]
ok, it = A.hall_wiring([1, 3, 2, 6, 4, 5, 1]); assert ok and it[-1][0] == "ok"
ok, it = A.hall_wiring([1, 3, 1, 3]); assert not ok and any("missing" in t for _, t in it)
ok, it = A.hall_wiring([1, 3, 5, 1]); assert not ok and any("Sensor" in t and "never changed" in t for _, t in it), it   # B and C ... states 1,3,5: bit 2 (B) flips, bit 4 (C) flips; A always 1
assert any("Sensor A never changed" in t for _, t in it)
d = L.SimLink(); seen = set()
for _ in range(60):
    d.turn_by_hand(1 / 7 / 6 * 0.5); seen.add(d.get(M.LIVE["hall"]))
assert seen == set(M.HALL_LEGAL), seen
d.hall_dead = True; assert d.get(M.LIVE["hall"]) == 7
for k in ("motor.config.direction", "encoder.config.ignore_illegal_hall_state", "encoder.config.enable_phase_interpolation"):
    assert d.get(M.a(k)) is not None
print("PASS motor core")
