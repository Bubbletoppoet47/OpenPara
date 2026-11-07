"""
motor_model.py - what the Motor Control add-on knows about an ODrive-style board (ODESC, ODrive v3.x, firmware 0.5.x):
the settings it shows (path on the board, label, unit, plain-words hint), the numbers behind the enum settings, and the error bits in words.
The ASCII protocol the board speaks over USB (r path / w path value) reaches every one of these paths.  The names are those of firmware 0.5.x;
another firmware may lack some of them (the app then says "not on this board" and carries on).
"""
AXIS = "axis0"

STATES = {0: "Undefined", 1: "Idle", 2: "Start-up sequence", 3: "Full calibration", 4: "Motor calibration", 5: "Sensorless control",
          6: "Encoder index search", 7: "Encoder offset calibration", 8: "Closed loop control", 9: "Lock-in spin", 10: "Encoder direction find",
          11: "Homing", 12: "Hall polarity calibration", 13: "Hall phase calibration"}
IDLE, FULL_CAL, MOTOR_CAL, ENC_OFFSET_CAL, CLOSED_LOOP, HALL_POLARITY, HALL_PHASE = 1, 3, 4, 7, 8, 12, 13

MOTOR_TYPES = {0: "High current (normal brushless)", 2: "Gimbal motor", 3: "AC induction"}
ENCODER_MODES = {0: "Incremental (A / B / index)", 1: "Hall sensors", 2: "Sin / cos", 256: "SPI absolute (CUI)", 257: "SPI absolute (AMS, AS5047 / AS5048)",
                 258: "SPI absolute (AEAT)", 259: "SPI absolute (RLS)", 260: "SPI absolute (MA732)"}
CONTROL_MODES = {0: "Voltage", 1: "Torque (current)", 2: "Velocity", 3: "Position"}
INPUT_MODES = {0: "Inactive", 1: "Pass-through", 2: "Velocity ramp", 3: "Position filter", 5: "Trapezoidal trajectory", 6: "Torque ramp"}
HALL_MODE = 1


class F:
    """One setting: where it is on the board and how it is shown."""
    def __init__(self, path, label, kind="float", unit="", tip="", enum=None, lo=None, hi=None, decimals=4):
        self.path, self.label, self.kind, self.unit, self.tip, self.enum = path, label, kind, unit, tip, enum
        self.lo, self.hi, self.decimals = lo, hi, decimals


def a(s):
    return f"{AXIS}.{s}"


MOTOR_FIELDS = [
    F(a("motor.config.motor_type"), "Motor type", "enum", enum=MOTOR_TYPES, tip="Almost every brushless motor is 'High current'."),
    F(a("motor.config.pole_pairs"), "Pole pairs", "int", lo=1, hi=100,
      tip="Magnet pairs of the rotor (the number of magnets divided by 2). It decides how many Hall steps there are in one turn."),
    F(a("motor.config.current_lim"), "Current limit", "float", "A", "The most phase current the board lets through. Start low (a few amps) until the motor is tuned.", lo=0, hi=200, decimals=2),
    F(a("motor.config.calibration_current"), "Calibration current", "float", "A", "The current used to measure the motor. Higher gives a better measurement but heats the motor.", lo=0, hi=100, decimals=2),
    F(a("motor.config.resistance_calib_max_voltage"), "Max calibration voltage", "float", "V", "Upper limit of the voltage used while measuring the resistance.", lo=0, hi=60, decimals=2),
    F(a("motor.config.torque_constant"), "Torque constant", "float", "N m / A", "Torque per amp. About 8.27 divided by the motor's KV rating.", lo=0, hi=10, decimals=5),
]
SENSOR_FIELDS = [
    F(a("encoder.config.mode"), "Sensor type", "enum", enum=ENCODER_MODES, tip="Hall sensors give a few steps per turn; an encoder gives hundreds or thousands."),
    F(a("encoder.config.cpr"), "Counts per turn", "int", "", "For Hall sensors: 6 x pole pairs. For an incremental encoder: 4 x the lines per turn. For an absolute SPI encoder: its resolution (e.g. 16384).", lo=1, hi=1000000),
    F(a("encoder.config.use_index"), "Use the index pulse", "bool", tip="Only for incremental encoders that have an index (Z) pulse."),
    F(a("encoder.config.bandwidth"), "Sensor filter bandwidth", "float", "rad/s", "How fast the position / speed estimate follows the sensor. Higher is quicker but noisier. Hall sensors usually need a low value.", lo=1, hi=20000, decimals=1),
    F(a("encoder.config.calib_range"), "Calibration tolerance", "float", "", "How far the sensor reading may be from the expected one during calibration before it is called an error.", lo=0, hi=5, decimals=3),
]
CONTROL_FIELDS = [
    F(a("controller.config.control_mode"), "Control mode", "enum", enum=CONTROL_MODES, tip="What the board controls: torque, speed or position."),
    F(a("controller.config.input_mode"), "Input mode", "enum", enum=INPUT_MODES, tip="How commands are turned into targets (ramps and filters make the motion smoother)."),
    F(a("controller.config.pos_gain"), "Position gain", "float", "(turn/s) / turn", "How hard the position loop pulls toward the target.", lo=0, hi=1000, decimals=3),
    F(a("controller.config.vel_gain"), "Speed gain", "float", "A / (turn/s)", "How hard the speed loop pushes. Too high makes the motor buzz or oscillate.", lo=0, hi=100, decimals=4),
    F(a("controller.config.vel_integrator_gain"), "Speed integrator gain", "float", "A / turn", "Removes a steady speed error; too high makes it overshoot.", lo=0, hi=1000, decimals=4),
    F(a("controller.config.vel_limit"), "Speed limit", "float", "turn/s", "The board never commands more speed than this.", lo=0, hi=1000, decimals=3),
]
BOARD_FIELDS = [
    F("config.dc_bus_undervoltage_trip_level", "Under-voltage trip", "float", "V", "The board stops if the supply falls below this.", lo=0, hi=60, decimals=2),
    F("config.dc_bus_overvoltage_trip_level", "Over-voltage trip", "float", "V", "The board stops if the supply rises above this (braking pushes it up).", lo=0, hi=80, decimals=2),
    F("config.brake_resistance", "Brake resistance", "float", "ohm", "The resistance of the brake resistor, if there is one.", lo=0, hi=100, decimals=3),
    F("config.enable_brake_resistor", "Brake resistor fitted", "bool", tip="Tick only if a brake resistor is connected."),
]
SECTIONS = {"motor": MOTOR_FIELDS, "sensor": SENSOR_FIELDS, "control": CONTROL_FIELDS, "board": BOARD_FIELDS}
ALL_FIELDS = [f for fs in SECTIONS.values() for f in fs]

# live values
LIVE = {"pos": a("encoder.pos_estimate"), "vel": a("encoder.vel_estimate"), "iq": a("motor.current_control.Iq_measured"), "vbus": "vbus_voltage",
        "state": a("current_state"), "err": a("error"), "merr": a("motor.error"), "eerr": a("encoder.error"), "cerr": a("controller.error")}
INFO = ["fw_version_major", "fw_version_minor", "fw_version_revision", "hw_version_major", "hw_version_minor", "serial_number"]
CAL_RESULT = {"R": a("motor.config.phase_resistance"), "L": a("motor.config.phase_inductance"), "motor_ok": a("motor.is_calibrated"),
              "enc_ready": a("encoder.is_ready"), "offset": a("encoder.config.offset"), "pre_cal": a("encoder.config.pre_calibrated")}

AXIS_ERRORS = {0x1: "Invalid state (the board refused the command: not calibrated yet?)", 0x2: "Supply voltage too low", 0x4: "Supply voltage too high",
               0x8: "Current measurement timed out", 0x10: "Brake resistor disarmed", 0x20: "Motor disarmed", 0x40: "Motor failed", 0x80: "Sensorless estimator failed",
               0x100: "Sensor failed", 0x200: "Controller failed", 0x400: "Position control during sensorless", 0x800: "Watchdog timer expired"}
MOTOR_ERRORS = {0x1: "Phase resistance out of range (bad motor or wiring)", 0x2: "Phase inductance out of range (bad motor or wiring)", 0x4: "Current sensor (ADC) failed",
                0x8: "Gate driver fault", 0x10: "Control loop missed its deadline", 0x20: "Motor type not supported", 0x40: "Brake current out of range",
                0x80: "Modulation too large", 0x100: "Brake dead-time violation", 0x200: "Unexpected timer callback", 0x400: "Current sensor saturated",
                0x1000: "Current limit exceeded", 0x10000: "Modulation is not a number", 0x20000: "Motor too hot", 0x40000: "Board (FET) too hot",
                0x80000: "Timer update missed", 0x100000: "Current measurement unavailable", 0x200000: "Controller failed", 0x400000: "Bus current out of range",
                0x800000: "Brake resistor disarmed"}
ENCODER_ERRORS = {0x1: "Unstable sensor gain (lower the filter bandwidth)", 0x2: "Counts per turn does not match the pole pairs (Hall: it must be 6 x pole pairs)",
                  0x4: "No response from the sensor", 0x8: "Sensor type not supported", 0x10: "Illegal Hall state (a Hall wire is loose or swapped)",
                  0x20: "Index pulse not found yet", 0x40: "SPI sensor timed out", 0x80: "SPI sensor communication failed", 0x100: "SPI sensor not ready"}
CONTROLLER_ERRORS = {0x1: "Over speed (above the speed limit)", 0x2: "Invalid input mode", 0x4: "Unstable gain", 0x8: "Invalid mirror axis", 0x10: "Invalid load encoder",
                     0x20: "Invalid estimate", 0x40: "Invalid circular range", 0x80: "Spin-out detected (the motor ran away from the sensor)"}


def decode(value, table, what):
    """Words for the error bits set in `value` (an int)."""
    v = int(value or 0)
    out = []
    for bit, text in table.items():
        if v & bit:
            out.append(text)
            v &= ~bit
    if v:
        out.append(f"{what} error bits 0x{v:X} (not known to this app)")
    return out


def error_report(axis, motor, encoder, controller):
    """A list of plain sentences for the four error words; empty when all is well."""
    return (decode(axis, AXIS_ERRORS, "Axis") + decode(motor, MOTOR_ERRORS, "Motor") + decode(encoder, ENCODER_ERRORS, "Sensor")
            + decode(controller, CONTROLLER_ERRORS, "Controller"))


def suggested_cpr(mode, pole_pairs):
    """Hall sensors: six steps per electrical turn."""
    return 6 * int(pole_pairs) if int(mode) == HALL_MODE else None


def check_calibration(res, pole_pairs=None):
    """Plain-words remarks on motor calibration results {R, L, ...} (ohm, henry); a list of (level, text) with level ok / warn / bad."""
    out = []
    R, L = res.get("R"), res.get("L")
    if R is None or L is None:
        return [("warn", "No motor calibration result on the board yet.")]
    if R <= 0:
        out.append(("bad", "The resistance is zero: the motor is not calibrated, or a phase wire is not connected."))
    elif R < 0.005:
        out.append(("warn", f"{R * 1000:.1f} milliohm is very low: fine for a big motor, but check the wires if it is a small one."))
    elif R > 2.0:
        out.append(("warn", f"{R:.2f} ohm is high for a brushless motor: check the connections and the calibration current."))
    else:
        out.append(("ok", f"Resistance {R * 1000:.1f} milliohm looks reasonable."))
    if L and L > 0:
        out.append(("ok" if 2e-6 < L < 5e-3 else "warn", f"Inductance {L * 1e6:.1f} microhenry" + ("" if 2e-6 < L < 5e-3 else " is unusual: check the motor and wiring.")))
    else:
        out.append(("bad", "The inductance is zero: the motor is not calibrated."))
    return out
