"""
motor_link.py - talking to the board.
SerialLink: the ODrive ASCII protocol over the USB serial port (pyserial; no driver install needed on most systems).
SimLink:    a simulated ODESC with a motor, used for the demo mode and for all tests - nothing here touches hardware.
Both offer the same small API: get(path) / set(path, value) / save() / erase() / reboot() / info() / advance(dt) / now() / close().
get() returns a number, or None when the board does not have that path.
"""
import math
import time

import motor_model as M


def list_ports():
    """[(device, description)] of serial ports; empty if pyserial is not installed."""
    try:
        from serial.tools import list_ports as lp
    except Exception:
        return []
    return [(p.device, p.description or p.device) for p in lp.comports()]


class LinkError(Exception):
    pass


class SerialLink:
    sim = False

    def __init__(self, port, baud=115200, timeout=0.4):
        try:
            import serial
        except Exception as e:
            raise LinkError("The serial library (pyserial) is not installed. Install the Motor Control add-on again from the Add-ons dialog.") from e
        try:
            self.ser = serial.Serial(port, baud, timeout=timeout)
        except Exception as e:
            raise LinkError(f"Could not open {port}: {e}") from e
        self.t0 = time.time()
        self.ser.reset_input_buffer()

    def now(self):
        return time.time() - self.t0

    def advance(self, dt):
        pass

    def _line(self, text):
        self.ser.write((text + "\n").encode())
        return self.ser.readline().decode(errors="replace").strip()

    def get(self, path):
        try:
            r = self._line("r " + path)
        except Exception as e:
            raise LinkError(f"Lost the connection: {e}") from e
        if r == "" or r.lower() in ("invalid property", "0 invalid property"):
            return None
        try:
            return float(r) if any(c in r for c in ".en") and r.lower() not in ("true", "false") else int(r)
        except ValueError:
            return {"true": 1, "false": 0}.get(r.lower())

    def set(self, path, value):
        if isinstance(value, bool):
            value = int(value)
        try:
            self.ser.write(f"w {path} {value}\n".encode())
        except Exception as e:
            raise LinkError(f"Lost the connection: {e}") from e

    def command(self, cmd):
        try:
            self.ser.write((cmd + "\n").encode())
        except Exception as e:
            raise LinkError(f"Lost the connection: {e}") from e

    def save(self):
        self.command("ss")

    def erase(self):
        self.command("se")

    def reboot(self):
        self.command("sr")

    def info(self):
        d = {k: self.get(k) for k in M.INFO}
        return d

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def _defaults():
    return {
        "axis0.motor.config.motor_type": 0, "axis0.motor.config.pole_pairs": 7, "axis0.motor.config.current_lim": 10.0,
        "axis0.motor.config.calibration_current": 10.0, "axis0.motor.config.resistance_calib_max_voltage": 2.0,
        "axis0.motor.config.torque_constant": 0.04, "axis0.motor.config.phase_resistance": 0.0, "axis0.motor.config.phase_inductance": 0.0,
        "axis0.motor.is_calibrated": 0,
        "axis0.encoder.config.mode": 0, "axis0.encoder.config.cpr": 4000, "axis0.encoder.config.use_index": 0,
        "axis0.encoder.config.bandwidth": 1000.0, "axis0.encoder.config.calib_range": 0.02, "axis0.encoder.config.offset": 0,
        "axis0.encoder.config.pre_calibrated": 0, "axis0.encoder.is_ready": 0,
        "axis0.controller.config.control_mode": 3, "axis0.controller.config.input_mode": 1, "axis0.controller.config.pos_gain": 20.0,
        "axis0.controller.config.vel_gain": 0.16, "axis0.controller.config.vel_integrator_gain": 0.32, "axis0.controller.config.vel_limit": 20.0,
        "config.dc_bus_undervoltage_trip_level": 8.0, "config.dc_bus_overvoltage_trip_level": 30.0, "config.brake_resistance": 2.0,
        "config.enable_brake_resistor": 0, "axis0.requested_state": 0, "axis0.controller.input_pos": 0.0, "axis0.controller.input_vel": 0.0,
        "axis0.controller.input_torque": 0.0,
    }


class SimLink:
    """A pretend ODESC V4.2 with a small brushless motor. Realistic enough to show the Hall-sensor limits: coarse position, rough speed at low speed."""
    sim = True
    HW = {"fw_version_major": 0, "fw_version_minor": 5, "fw_version_revision": 4, "hw_version_major": 3, "hw_version_minor": 6, "serial_number": 1234567}

    def __init__(self, vbus=24.0, R=0.12, L=45e-6, J=2.0e-5, friction=2.0e-4, kt=0.04):
        self.cfg = _defaults()
        self.cfg["axis0.motor.config.torque_constant"] = kt
        self.vbus, self.R, self.L, self.J, self.fric, self.kt = vbus, R, L, J, friction, kt
        self.t = 0.0
        self.theta = 0.0          # true rotor angle, turns
        self.omega = 0.0          # true speed, turn/s
        self.iq = 0.0
        self.state = M.IDLE
        self.err = {"axis": 0, "motor": 0, "encoder": 0, "controller": 0}
        self.cal_left = 0.0
        self.cal_chain = []
        self.pos_est = 0.0
        self.vel_est = 0.0
        self.integ = 0.0
        self.pos_off = 0.0
        self.polarity = 1
        self.hall_ok = False
        self.disturb = 0.0        # external torque N m, set by tests / the demo
        self.wires_swapped = False
        self.saved = dict(self.cfg)
        self.bad_hall = False
        # uneven Hall edges: real magnets/sensors are never exactly 60 degrees apart
        self.edge_err = [0.0, 0.035, -0.03, 0.02, -0.04, 0.025]

    # -- time ---------------------------------------------------------------------------------------------------------
    def now(self):
        return self.t

    def advance(self, dt):
        n = max(1, int(round(dt / 0.001)))
        h = dt / n
        for _ in range(n):
            self._step(h)

    # -- hall sensor model -----------------------------------------------------------------------------------------------
    def _hall_pos(self):
        """Position (turns) as the Hall sensors report it: steps of 1/(6 pp), edges slightly misplaced."""
        pp = max(1, int(self.cfg["axis0.motor.config.pole_pairs"]))
        e = self.theta * pp
        k = math.floor(e * 6 / 1.0 + 1e-12)          # hall step index over the whole run
        ph = k % 6
        # edge of step k sits at its nominal place plus a small fixed error
        nominal = k / 6.0
        pos = (nominal + self.edge_err[ph] / 6.0) / pp
        return pos

    def _sensor_pos(self):
        mode = int(self.cfg["axis0.encoder.config.mode"])
        if mode == M.HALL_MODE:
            return self._hall_pos()
        cpr = max(1, int(self.cfg["axis0.encoder.config.cpr"]))
        return math.floor(self.theta * cpr) / cpr

    # -- physics ----------------------------------------------------------------------------------------------------------
    def _fail(self, kind, bit, axis_bit=None):
        self.err[kind] |= bit
        self.err["axis"] |= axis_bit or {"motor": 0x40, "encoder": 0x100, "controller": 0x200}.get(kind, 0)
        self._to_idle()

    def _to_idle(self):
        self.state = M.IDLE
        self.cal_chain = []
        self.cal_left = 0
        self.iq = 0.0

    def _step(self, h):
        self.t += h
        c = self.cfg
        req = int(c["axis0.requested_state"])
        if req:
            c["axis0.requested_state"] = 0
            self._request(req)
        # supply check
        if self.state != M.IDLE and not self.err["axis"]:
            if self.vbus < c["config.dc_bus_undervoltage_trip_level"]:
                self.err["axis"] |= 0x2
                self._to_idle()
            elif self.vbus > c["config.dc_bus_overvoltage_trip_level"]:
                self.err["axis"] |= 0x4
                self._to_idle()
        # calibration sequence
        if self.cal_chain and self.state != M.CLOSED_LOOP:
            self.cal_left -= h
            if self.cal_left <= 0:
                self._finish(self.state)
                if self.cal_chain:
                    self._begin(self.cal_chain.pop(0))
                elif not self.err["axis"]:
                    self.state = M.IDLE
        elif self.state in (M.MOTOR_CAL, M.HALL_POLARITY, M.HALL_PHASE, M.ENC_OFFSET_CAL):
            self.cal_left -= h
            if self.cal_left <= 0:
                self._finish(self.state)
                if not self.err["axis"]:
                    self.state = M.IDLE
        # control
        if self.state == M.CLOSED_LOOP:
            self._control(h)
        else:
            self.iq *= 0.9
        # mechanics (torque from iq, friction, disturbance)
        tq = self.kt * self.iq - self.disturb
        acc = (tq - self.fric * self.omega * 6.2832 - (0.002 * (1 if self.omega > 0 else -1 if self.omega < 0 else 0))) / self.J / 6.2832
        if self.state != M.CLOSED_LOOP and abs(self.omega) < 0.05 and abs(self.disturb) < 0.002:
            self.omega = 0.0
        else:
            self.omega += acc * h
        self.theta += self.omega * h
        # sensor estimator (PLL), the same structure as the board's
        sp = self._sensor_pos()
        bw = max(1.0, c["axis0.encoder.config.bandwidth"])
        kp, ki = 2 * bw, 0.25 * (2 * bw) ** 2
        for _ in range(8):                               # the board runs this at 8 kHz; we step the sim at 1 kHz
            er = sp - self.pos_est
            self.pos_est += h / 8 * (self.vel_est + kp * er)
            self.vel_est += h / 8 * ki * er

    def _begin(self, st):
        self.state = st
        self.cal_left = {M.MOTOR_CAL: 4.0, M.HALL_POLARITY: 2.0, M.HALL_PHASE: 3.0, M.ENC_OFFSET_CAL: 3.0}.get(st, 1.0)

    def _request(self, st):
        c = self.cfg
        if st == M.IDLE:
            self._to_idle()
            return
        if self.err["axis"] and st != M.IDLE:
            self.err["axis"] |= 0x1
            return
        if self.state != M.IDLE and st != M.CLOSED_LOOP:
            return
        mode = int(c["axis0.encoder.config.mode"])
        if st == M.FULL_CAL:
            self.cal_chain = [M.MOTOR_CAL] + ([M.HALL_POLARITY, M.HALL_PHASE] if mode == M.HALL_MODE else [M.ENC_OFFSET_CAL])
            self._begin(self.cal_chain.pop(0))
        elif st in (M.MOTOR_CAL, M.HALL_POLARITY, M.HALL_PHASE, M.ENC_OFFSET_CAL):
            if st != M.MOTOR_CAL and not c["axis0.motor.is_calibrated"]:
                self.err["axis"] |= 0x1
                return
            self._begin(st)
        elif st == M.CLOSED_LOOP:
            if not c["axis0.motor.is_calibrated"] or not c["axis0.encoder.is_ready"]:
                self.err["axis"] |= 0x1
                return
            self.state = M.CLOSED_LOOP
            self.integ = 0.0
            c["axis0.controller.input_pos"] = self.pos_est
        else:
            self.err["axis"] |= 0x1

    def _finish(self, st):
        c = self.cfg
        mode = int(c["axis0.encoder.config.mode"])
        if st == M.MOTOR_CAL:
            lim = c["axis0.motor.config.resistance_calib_max_voltage"]
            if c["axis0.motor.config.calibration_current"] * self.R > lim:
                self._fail("motor", 0x1)
                return
            c["axis0.motor.config.phase_resistance"] = self.R
            c["axis0.motor.config.phase_inductance"] = self.L
            c["axis0.motor.is_calibrated"] = 1
        elif st == M.HALL_POLARITY:
            if self.bad_hall:
                self._fail("encoder", 0x10)
        elif st == M.HALL_PHASE:
            pp = int(c["axis0.motor.config.pole_pairs"])
            if int(c["axis0.encoder.config.cpr"]) != 6 * pp:
                self._fail("encoder", 0x2)
                return
            c["axis0.encoder.is_ready"] = 1
        elif st == M.ENC_OFFSET_CAL:
            c["axis0.encoder.is_ready"] = 1
            c["axis0.encoder.config.offset"] = 123

    def _control(self, h):
        c = self.cfg
        mode = int(c["axis0.controller.config.control_mode"])
        lim = c["axis0.motor.config.current_lim"]
        vlim = c["axis0.controller.config.vel_limit"]
        if abs(self.vel_est) > vlim * 1.2:
            self._fail("controller", 0x1)
            return
        if mode == 1:
            cmd = c["axis0.controller.input_torque"] / max(self.kt, 1e-6)
        else:
            if mode == 3:
                vcmd = c["axis0.controller.config.pos_gain"] * (c["axis0.controller.input_pos"] - self.pos_est) + 0.0
            else:
                vcmd = c["axis0.controller.input_vel"]
            vcmd = max(-vlim, min(vlim, vcmd))
            ev = vcmd - self.vel_est
            self.integ += c["axis0.controller.config.vel_integrator_gain"] * ev * h
            self.integ = max(-lim, min(lim, self.integ))
            cmd = c["axis0.controller.config.vel_gain"] * ev + self.integ
        self.iq = max(-lim, min(lim, cmd))

    # -- the API --------------------------------------------------------------------------------------------------------------
    def get(self, path):
        c = self.cfg
        if path == M.LIVE["pos"]:
            return self.pos_est
        if path == M.LIVE["vel"]:
            return self.vel_est
        if path == M.LIVE["iq"]:
            return self.iq
        if path == M.LIVE["vbus"]:
            return self.vbus
        if path == M.LIVE["state"]:
            return self.state
        if path == M.LIVE["err"]:
            return self.err["axis"]
        if path == M.LIVE["merr"]:
            return self.err["motor"]
        if path == M.LIVE["eerr"]:
            return self.err["encoder"]
        if path == M.LIVE["cerr"]:
            return self.err["controller"]
        if path in self.HW:
            return self.HW[path]
        return c.get(path)

    def set(self, path, value):
        if isinstance(value, bool):
            value = int(value)
        if path in self.cfg:
            self.cfg[path] = value
        if path == "axis0.motor.config.pole_pairs" or path == "axis0.motor.config.motor_type":
            self.cfg["axis0.motor.is_calibrated"] = 0
            self.cfg["axis0.encoder.is_ready"] = 0
        if path == "axis0.encoder.config.mode":
            self.cfg["axis0.encoder.is_ready"] = 0

    def clear_errors(self):
        for k in self.err:
            self.err[k] = 0

    def save(self):
        self.saved = dict(self.cfg)

    def erase(self):
        self.cfg = _defaults()
        self.cfg["axis0.motor.config.torque_constant"] = self.kt
        self.saved = dict(self.cfg)

    def reboot(self):
        self.cfg = dict(self.saved)
        self.state = M.IDLE
        self.clear_errors()
        self.omega = 0.0
        self.iq = 0.0

    def info(self):
        return dict(self.HW)

    def close(self):
        pass
