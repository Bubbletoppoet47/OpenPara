"""
lidar_udp_reader.py

A from-scratch Python reader for the Unitree 4D LiDAR L2, talking directly
to it over Ethernet/UDP - no vendor app, no C++ build required. This exists
because Unitree doesn't actually ship a standalone Windows viewer app (the
"Unilidar 2 User Manual" describes software that isn't separately
downloadable); all they publish is the closed-source C++ SDK
(unilidar_sdk2), which only builds on Linux.

Everything this script needs was pulled directly from that SDK's own
headers (which are just data + open, readable math - not reverse
engineered) and cross-checked by compiling a tiny C++ probe against them
to get ground-truth struct sizes/offsets, since a couple of the header's
own doc comments turned out to be stale:
  - unitree_lidar_sdk2/unitree_lidar_sdk/include/unitree_lidar_protocol.h
    (wire format: frame header/tail, packet types, struct layouts)
  - unitree_lidar_sdk2/unitree_lidar_sdk/include/unitree_lidar_utilities.h
    (parseFromPacketToPointCloud - the raw-scan-line -> XYZ math)

The one part that ISN'T pulled from readable source: the SDK's actual
socket/command-sending code lives only as compiled object code inside
libunitree_lidar_sdk2.a, not as headers, so the outbound CRC's byte range
wasn't documented anywhere. It's now been confirmed empirically instead
(see lidar_command_probe.py): the CRC32 in the tail covers ONLY the
8-byte command payload (cmd_type + cmd_value), not the 12-byte frame
header, and msg_type_check is 0. build_user_ctrl_cmd_packet() below uses
that confirmed formula - verified against real hardware via ACK_SUCCESS
plus an actual stop/resume of rotation, not just a guess anymore.

Setup (matches what we already worked out for the vendor app):
  1. Give your Ethernet adapter the static IP 192.168.1.2 / 255.255.255.0
  2. Plug the L2 in via Ethernet and power it on
  3. Run this script - no admin/root needed, it's just a UDP socket

Usage:
    python lidar_udp_reader.py
    python lidar_udp_reader.py --local-port 6201
    python lidar_udp_reader.py --no-start-command   # just listen, don't send anything
"""
import argparse
import math
import socket
import struct
import sys
import time
import zlib

import numpy as np

# ---------------------------------------------------------------------------
# Wire format constants (from unitree_lidar_protocol.h)
# ---------------------------------------------------------------------------

FRAME_HEADER_MAGIC = bytes([0x55, 0xAA, 0x05, 0x0A])
FRAME_TAIL_MAGIC = bytes([0x00, 0xFF])

LIDAR_USER_CMD_PACKET_TYPE = 100
LIDAR_ACK_DATA_PACKET_TYPE = 101
LIDAR_POINT_DATA_PACKET_TYPE = 102
LIDAR_2D_POINT_DATA_PACKET_TYPE = 103
LIDAR_IMU_DATA_PACKET_TYPE = 104
LIDAR_VERSION_PACKET_TYPE = 105
LIDAR_WORK_MODE_CONFIG_PACKET_TYPE = 107

# LidarUserCtrlCmd.cmd_type values
USER_CMD_STANDBY_TYPE = 2   # cmd_value 0: start: cmd_value 1: standby

ACK_STATUS_NAMES = {
    1: "ACK_SUCCESS",
    2: "ACK_CRC_ERROR",
    3: "ACK_HEADER_ERROR",
    4: "ACK_BLOCK_ERROR",
    5: "ACK_WAIT_ERROR (data not ready)",
}

FRAME_HEADER_SIZE = 12  # 4-byte magic + uint32 packet_type + uint32 packet_size
FRAME_TAIL_SIZE = 12    # uint32 crc32 + uint32 msg_type_check + 2 reserve + 2 tail magic

# Ground-truth byte offsets/sizes for LidarPointData, confirmed by compiling
# a small probe against the real header (the header's own "@note N bytes"
# comments for this struct and for LidarImuData/LidarVersionData turned out
# to be stale - these numbers are compiler-verified, not from the comments).
POINT_DATA_SIZE = 1020
POINT_DATA_OFF_INFO = 0
POINT_DATA_OFF_STATE = 16
POINT_DATA_OFF_PARAM = 52
POINT_DATA_OFF_SCALARS = 84   # com_horizontal_angle_start .. point_num
POINT_DATA_OFF_RANGES = 120   # uint16[300]
POINT_DATA_OFF_INTENSITIES = 720  # uint8[300]
POINT_DATA_NUM_RANGES = 300

IMU_DATA_SIZE = 56
VERSION_DATA_SIZE = 80
ACK_DATA_SIZE = 16
USER_CTRL_CMD_PACKET_SIZE = 32  # compiler-verified: header(12) + cmd(8) + tail(12)

# ---------------------------------------------------------------------------
# Struct format strings (all little-endian, matching the compiled offsets)
# ---------------------------------------------------------------------------

_HEADER_FMT = struct.Struct("<4sII")                # magic, packet_type, packet_size
_TAIL_FMT = struct.Struct("<II2s2s")                # crc32, msg_type_check, reserve, tail

# LidarCalibParam: 8 floats (a_axis_dist, b_axis_dist, theta_angle_bias,
# alpha_angle_bias, beta_angle, xi_angle, range_bias, range_scale)
_PARAM_FMT = struct.Struct("<8f")

# The 9 scalar fields between "param" and the ranges/intensities arrays:
# com_horizontal_angle_start, com_horizontal_angle_step, scan_period,
# range_min, range_max, angle_min, angle_increment, time_increment, point_num
_SCALARS_FMT = struct.Struct("<8fI")

_RANGES_FMT = struct.Struct(f"<{POINT_DATA_NUM_RANGES}H")
_INTENSITIES_FMT = struct.Struct(f"<{POINT_DATA_NUM_RANGES}B")

# LidarImuData: DataInfo(seq, payload_size, stamp.sec, stamp.nsec) +
# quaternion[4] + angular_velocity[3] + linear_acceleration[3]
_IMU_FMT = struct.Struct("<IIII4f3f3f")

# LidarVersionData: hw_version[4], sw_version[4], name[24], date[8], reserve[40]
_VERSION_FMT = struct.Struct("<4s4s24s8s40s")

# LidarAckData: packet_type, cmd_type, cmd_value, status (all uint32)
_ACK_FMT = struct.Struct("<IIII")

# LidarUserCtrlCmd: cmd_type, cmd_value (both uint32)
_USER_CTRL_CMD_FMT = struct.Struct("<II")


def build_user_ctrl_cmd_packet(cmd_type: int, cmd_value: int) -> bytes:
    """
    Build a LidarUserCtrlCmdPacket. CRC formula confirmed against real
    hardware by lidar_command_probe.py: crc32 over the 8-byte command
    payload only (header is NOT included), msg_type_check = 0.
    """
    data = _USER_CTRL_CMD_FMT.pack(cmd_type, cmd_value)
    header = _HEADER_FMT.pack(FRAME_HEADER_MAGIC, LIDAR_USER_CMD_PACKET_TYPE,
                               USER_CTRL_CMD_PACKET_SIZE)
    crc = zlib.crc32(data) & 0xFFFFFFFF
    tail = _TAIL_FMT.pack(crc, 0, b"\x00\x00", FRAME_TAIL_MAGIC)
    return header + data + tail


def parse_point_cloud(data: bytes):
    """
    Vectorized port of parseFromPacketToPointCloud() from
    unitree_lidar_utilities.h. `data` is the 1020-byte LidarPointData
    payload (i.e. the packet with the 12-byte frame header and 12-byte
    frame tail already stripped off).

    Returns an (M, 4) numpy array of [x, y, z, intensity] rows in meters.
    This used to be a pure-Python per-point loop with a couple of
    math.sin/cos calls per point; at ~55-60k points/sec that loop was the
    main source of lag (both its own cost, and it hogging the GIL and
    starving the plotting thread). Verified against the original
    scalar-loop version on synthetic data - identical output.
    """
    (a_axis_dist, b_axis_dist, theta_angle_bias, alpha_angle_bias,
     beta_angle, xi_angle, range_bias, range_scale) = _PARAM_FMT.unpack_from(
        data, POINT_DATA_OFF_PARAM)

    (horiz_start, horiz_step, scan_period, range_min, range_max,
     angle_min, angle_increment, time_increment, point_num) = \
        _SCALARS_FMT.unpack_from(data, POINT_DATA_OFF_SCALARS)

    num_of_points = int(min(point_num, POINT_DATA_NUM_RANGES))

    ranges = np.frombuffer(data, dtype="<u2", count=POINT_DATA_NUM_RANGES,
                            offset=POINT_DATA_OFF_RANGES)[:num_of_points].astype(np.float64)
    intensities = np.frombuffer(data, dtype="<u1", count=POINT_DATA_NUM_RANGES,
                                 offset=POINT_DATA_OFF_INTENSITIES)[:num_of_points]

    j = np.arange(num_of_points, dtype=np.float64)
    alpha = angle_min + alpha_angle_bias + j * angle_increment
    theta = horiz_start + theta_angle_bias + j * horiz_step

    sin_beta, cos_beta = math.sin(beta_angle), math.cos(beta_angle)
    sin_xi, cos_xi = math.sin(xi_angle), math.cos(xi_angle)
    cos_beta_sin_xi = cos_beta * sin_xi
    sin_beta_cos_xi = sin_beta * cos_xi
    sin_beta_sin_xi = sin_beta * sin_xi
    cos_beta_cos_xi = cos_beta * cos_xi

    range_float = range_scale * (ranges + range_bias)
    valid = (ranges >= 1) & (range_float >= range_min) & (range_float <= range_max)

    sin_alpha = np.sin(alpha)
    cos_alpha = np.cos(alpha)
    sin_theta = np.sin(theta)
    cos_theta = np.cos(theta)

    A = (-cos_beta_sin_xi + sin_beta_cos_xi * sin_alpha) * range_float + b_axis_dist
    B = cos_alpha * cos_xi * range_float
    C = (sin_beta_sin_xi + cos_beta_cos_xi * sin_alpha) * range_float

    x = cos_theta * A - sin_theta * B
    y = sin_theta * A + cos_theta * B
    z = C + a_axis_dist

    x, y, z = x[valid], y[valid], z[valid]
    intensity = intensities[valid].astype(np.float64)

    return np.column_stack([x, y, z, intensity])

def parse_imu(data: bytes):
    seq, payload_size, stamp_sec, stamp_nsec, qx, qy, qz, qw, \
        wx, wy, wz, ax, ay, az = _IMU_FMT.unpack_from(data, 0)
    return {
        "seq": seq,
        "quaternion": (qx, qy, qz, qw),
        "angular_velocity": (wx, wy, wz),
        "linear_acceleration": (ax, ay, az),
    }


def parse_version(data: bytes):
    hw, sw, name, date, _reserve = _VERSION_FMT.unpack_from(data, 0)

    def clean(b: bytes) -> str:
        return b.split(b"\x00", 1)[0].decode("ascii", errors="replace")

    return {
        "hw_version": ".".join(str(b) for b in hw),
        "sw_version": ".".join(str(b) for b in sw),
        "name": clean(name),
        "date": clean(date),
    }


def parse_ack(data: bytes):
    packet_type, cmd_type, cmd_value, status = _ACK_FMT.unpack_from(data, 0)
    return {
        "packet_type": packet_type,
        "cmd_type": cmd_type,
        "cmd_value": cmd_value,
        "status": status,
        "status_name": ACK_STATUS_NAMES.get(status, f"unknown ({status})"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local-ip", default="0.0.0.0",
                     help="Local address to bind to (default: all interfaces)")
    ap.add_argument("--local-port", type=int, default=6201,
                     help="Local UDP port the L2 sends data to (default: 6201, "
                          "matches the L2's factory-default target port)")
    ap.add_argument("--lidar-ip", default="192.168.1.62",
                     help="L2's IP address (factory default: 192.168.1.62)")
    ap.add_argument("--lidar-port", type=int, default=6101,
                     help="L2's UDP port (factory default: 6101)")
    ap.add_argument("--no-start-command", action="store_true",
                     help="Just listen, don't send the experimental start command")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.local_ip, args.local_port))
    print(f"Listening for L2 UDP packets on {args.local_ip}:{args.local_port} ...")
    print("(If nothing arrives at all: check the static IP on your Ethernet "
          "adapter is 192.168.1.2/255.255.255.0, and that the L2 has power + "
          "link light.)")

    if not args.no_start_command:
        cmd_packet = build_user_ctrl_cmd_packet(USER_CMD_STANDBY_TYPE, 0)  # 0 = start
        sock.sendto(cmd_packet, (args.lidar_ip, args.lidar_port))
        print(f"Sent experimental 'start rotation' command to "
              f"{args.lidar_ip}:{args.lidar_port} ({len(cmd_packet)} bytes). "
              f"Watch for an ACK packet below to see if the L2 accepted it.\n")

    last_report = time.time()
    cloud_packets_since_report = 0
    imu_packets_since_report = 0
    points_since_report = 0
    seen_packet_types = set()

    try:
        while True:
            packet, addr = sock.recvfrom(4096)

            if len(packet) < FRAME_HEADER_SIZE + FRAME_TAIL_SIZE:
                continue

            magic, packet_type, packet_size = _HEADER_FMT.unpack_from(packet, 0)
            if magic != FRAME_HEADER_MAGIC:
                print(f"[warn] bad frame header from {addr}: {magic!r}")
                continue

            if packet_type not in seen_packet_types:
                seen_packet_types.add(packet_type)
                print(f"[info] first time seeing packet_type={packet_type}, "
                      f"len={len(packet)} bytes")

            body = packet[FRAME_HEADER_SIZE:-FRAME_TAIL_SIZE]

            if packet_type == LIDAR_POINT_DATA_PACKET_TYPE and len(body) >= POINT_DATA_SIZE:
                points = parse_point_cloud(body)
                cloud_packets_since_report += 1
                points_since_report += len(points)
                if cloud_packets_since_report == 1:
                    print(f"\nFirst point-cloud scan line: {len(points)} valid points")
                    for p in points[:5]:
                        print(f"  x={p[0]:+.3f}  y={p[1]:+.3f}  z={p[2]:+.3f}  intensity={p[3]}")

            elif packet_type == LIDAR_IMU_DATA_PACKET_TYPE and len(body) >= IMU_DATA_SIZE:
                imu_packets_since_report += 1
                if imu_packets_since_report == 1:
                    imu = parse_imu(body)
                    print(f"\nFirst IMU packet: quaternion={imu['quaternion']}")

            elif packet_type == LIDAR_VERSION_PACKET_TYPE and len(body) >= VERSION_DATA_SIZE:
                v = parse_version(body)
                print(f"\nLiDAR version info: {v}")

            elif packet_type == LIDAR_ACK_DATA_PACKET_TYPE and len(body) >= ACK_DATA_SIZE:
                ack = parse_ack(body)
                print(f"\nACK received: {ack}")

            # Print a one-line throughput summary every second.
            now = time.time()
            if now - last_report >= 1.0:
                print(f"[{time.strftime('%H:%M:%S')}] "
                      f"{cloud_packets_since_report} scan-line packets "
                      f"({points_since_report} pts), "
                      f"{imu_packets_since_report} IMU packets in the last "
                      f"{now - last_report:.1f}s")
                last_report = now
                cloud_packets_since_report = 0
                imu_packets_since_report = 0
                points_since_report = 0

    except KeyboardInterrupt:
        print("\nStopped.")
        sock.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
