"""Motor Control tab: layout, demo board, settings, calibration, safe start/stop, Hall analysis, project folder, add-on registration."""
import os, tempfile
_ud = os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
open(os.path.join(_ud, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "render"]}')
import addons; addons.startup()
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
import motor_tab as mt, motor_model as M

# ---- registered like the other add-ons
assert "motor" in addons.known() and addons.tab_kinds()["motor"]["label"] == "Motor Control"
assert addons.status("motor") == "installed", addons.status("motor")

def run(w, secs, dt=0.02):
    for _ in range(int(secs / dt)):
        w.tick(dt)

w = mt.make_tab()
assert w.title() == "Motor Control" and not w.is_dirty()
heads = [s.head.text() for s in (w.sec_connect, w.sec_setup, w.sec_cal, w.sec_run, w.sec_sensor)]
for i, h in enumerate(heads, 1):
    assert f" {i} " in h, heads
assert len(w.later) == 3 and all(not s.isEnabled() for s in w.later), "tuning / ESP32 / balance parts are visible but greyed out"
assert not w.run_btn.isEnabled() and not w.cal_btn.isEnabled(), "nothing to run without a board"
w.tick(0.02)                                    # no board: harmless

# ---- demo board
w.connect_demo()
assert w.connected() and "DEMO" in w.info_lbl.text() and "firmware 0.5.4" in w.info_lbl.text()
assert w.run_btn.isEnabled() and not w.demo_btn.isEnabled()
f_mode = [f for f in M.SENSOR_FIELDS if f.path.endswith("mode")][0]
f_cpr = [f for f in M.SENSOR_FIELDS if f.path.endswith("cpr")][0]
f_pp = [f for f in M.MOTOR_FIELDS if f.path.endswith("pole_pairs")][0]
assert w.field_value(f_pp) == 7 and w.field_value(f_mode) == 0

# ---- refuses to run before calibration, in words
assert not w.start_run("run") and "not calibrated" in w.status.text(), w.status.text()

# ---- Hall setup: a wrong counts-per-turn is flagged and blocked
w.set_field(f_mode, 1)
w.set_field(f_cpr, 40); w.show_checks()
assert "6 x pole pairs = 42" in w.check_lbl.text(), w.check_lbl.text()
w.set_hall_cpr(4); assert w.field_value(f_cpr) == 28 and "60-degree" in w.check_lbl.text() and "Counts per turn" not in w.check_lbl.text().replace("counts per turn", "")
w.set_field(f_cpr, 40); w.show_checks()
w.set_hall_cpr(); assert w.field_value(f_cpr) == 42 and "6 x pole pairs" not in w.check_lbl.text()
assert "42 steps per turn" in w.hall_info.text()
assert "jumpy" in w.check_lbl.text()
f_bw = [f for f in M.SENSOR_FIELDS if f.path.endswith("bandwidth")][0]; w.set_field(f_bw, 100.0); w.show_checks(); assert "jumpy" not in w.check_lbl.text()
w.write_settings(); assert "Wrote" in w.status.text()
assert w.link.get(f_cpr.path) == 42 and w.link.get(f_mode.path) == 1

# ---- calibrate
assert w.calibrate() is True and w.cal_pending
run(w, 14)
assert not w.cal_pending and "Resistance" in w.cal_lbl.text() and "position sensor is calibrated" in w.cal_lbl.text(), w.cal_lbl.text()
assert w.link.get(M.CAL_RESULT["enc_ready"]) == 1

# ---- speed above the board's limit is refused; a normal run works and ends by itself
w.run_mode.setCurrentIndex(0); w.run_val.setValue(500.0)
assert not w.start_run("run") and "speed limit" in w.status.text()
w.run_val.setValue(2.0); w.run_dur.setValue(3.0)
assert w.start_run("run") and w.job is not None and w.link.state == M.CLOSED_LOOP
run(w, 1.5)
assert abs(w.link.omega - 2.0) < 0.4
run(w, 2.5)
assert w.job is None and w.link.state == M.IDLE and "finished" in w.status.text(), w.status.text()

# ---- STOP drops to idle at once
assert w.start_run("run"); run(w, 0.5)
w.stop_btn.click()
assert w.job is None and w.link.state == M.IDLE and w.run_btn.text() == "Start"
# ---- an error during a run stops it and says why in words
assert w.start_run("run"); run(w, 0.5)
w.link.vbus = 3.0                         # the supply collapses
run(w, 0.5)
assert w.job is None and w.link.state == M.IDLE and "Supply voltage too low" in w.err_lbl.text(), w.err_lbl.text()
assert not w.start_run("run") and "errors" in w.status.text()
w.link.vbus = 24.0; w.clear_btn.click(); assert w.err_lbl.text() == ""
# ---- settings cannot be written while running
assert w.start_run("run"); w.write_settings(); assert "Not written" in w.status.text(); w.stop()

# ---- Hall analysis
w.run_val.setValue(3.0); w.run_dur.setValue(4.0)
assert w.start_run("analyze"); run(w, 5)
txt = w.an_lbl.text()
assert w.job is None and "ripple" in txt.lower() and "Hall step" in txt, txt
assert len(w.last_rec) > 100
csvp = os.path.join(tempfile.mkdtemp(), "r.csv"); w.write_csv(csvp)
assert open(csvp).read().splitlines()[0].startswith("time_s,position_turns")

# ---- Hall wiring check: motor not powered, shaft turned by hand
w.toggle_hall_check(); assert w.hcheck is not None
for _ in range(80):
    w.link.turn_by_hand(1 / 7 / 6 * 0.5); w.tick(0.02)
    if w.hcheck is None: break
assert w.hcheck is None and "All six Hall states" in w.hc_lbl.text() and "Hall state" in w.live_lbl.text(), w.hc_lbl.text()
w.link.hall_dead = True; w.tick(0.02)
assert "skipped" in w.live_lbl.text()          # ignore-illegal is on: 0 and 7 are expected for 60-degree sensors
f_ign = [f for f in M.SENSOR_FIELDS if f.path.endswith("ignore_illegal_hall_state")][0]
w.set_field(f_ign, 0); w.write_settings(); w.tick(0.02)
assert "ILLEGAL" in w.live_lbl.text()
assert not w.calibrate() and "illegal state 7" in w.status.text(), w.status.text()
w.toggle_hall_check(); w.tick(0.02); w.tick(0.02); w.toggle_hall_check()
assert "stayed at 7" in w.hc_lbl.text() and "5 V" in w.hc_lbl.text()
w.link.hall_dead = False; w.set_field(f_ign, 1); w.write_settings(); w.tick(0.02)
# ---- backup / restore through the tab
cur = [f for f in M.MOTOR_FIELDS if f.path.endswith("current_lim")][0]
import motor_analysis as A
bk = A.backup_text(w.link); w.link.set(cur.path, 33.0)
assert w.apply_settings_text(bk) >= 1 and w.link.get(cur.path) == 10.0 and w.field_value(cur) == 10.0
assert w.apply_settings_text("nonsense") == 0 and "not a Motor Control" in w.status.text()

# ---- project folder round trip
w.set_field(cur, 6.5); w.on_field(); assert w.is_dirty() and w.title().endswith("*")
proj = os.path.join(tempfile.mkdtemp(), "bot.motor")
assert w.save_to(proj) and not w.is_dirty() and os.path.isfile(os.path.join(proj, "motor.json")) and os.path.isfile(os.path.join(proj, "recordings", "last_test.csv"))
w.shutdown()
w2 = mt.make_tab(None, proj)
assert w2.title() == "bot.motor" and w2.field_value(cur) == 6.5 and w2.field_value(f_mode) == 1 and not w2.is_dirty()
w2.shutdown()
bad = mt.make_tab(None, tempfile.mkdtemp()); assert "not a Motor Control project" in bad.status.text(); bad.shutdown()

# ---- disconnect stops everything
w3 = mt.make_tab(); w3.connect_demo(); w3.disconnect_board(); assert not w3.connected() and not w3.run_btn.isEnabled(); w3.shutdown()
print("PASS motor tab")

dv = mt.make_tab(); dv.attach(__import__("motor_link").SimLink(dev_build=True)); assert "development build" in dv.info_lbl.text(); dv.shutdown()
