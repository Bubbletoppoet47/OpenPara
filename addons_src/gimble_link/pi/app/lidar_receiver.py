"""
lidar_receiver.py - lightweight background receiver for the Unitree L2 UDP stream.

Same idea as the LidarReceiver in lidar_live_viewer.py, but with no matplotlib
(so it installs cleanly on a Raspberry Pi) and with a few extras used by the Pi app:
  * keeps the last few seconds of points, each packet stamped with its arrival time
  * snapshot(window=None, t_end=None) returns the points from [t_end - window, t_end]
"""
import socket
import threading
import time
from collections import deque

import numpy as np

from lidar_udp_reader import (
    FRAME_HEADER_MAGIC, FRAME_HEADER_SIZE, FRAME_TAIL_SIZE, LIDAR_IMU_DATA_PACKET_TYPE,
    LIDAR_POINT_DATA_PACKET_TYPE, POINT_DATA_SIZE, _HEADER_FMT, parse_point_cloud,
)


class LidarReceiver:
    def __init__(self, local_ip="0.0.0.0", local_port=6201, window_seconds=0.5, keep_seconds=4.0):
        self.window_seconds = window_seconds
        self.keep_seconds = keep_seconds
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        self._sock.bind((local_ip, local_port))
        self._sock.settimeout(0.5)
        self._lock = threading.Lock()
        self._chunks = deque()          # (t_recv, (M,4) array)
        self._running = False
        self._thread = None
        self.packets_received = 0
        self.points_received = 0
        self.last_packet_time = 0.0

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        self._sock.close()

    def _run(self):
        while self._running:
            try:
                packet, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(packet) < FRAME_HEADER_SIZE + FRAME_TAIL_SIZE:
                continue
            magic, ptype, _ = _HEADER_FMT.unpack_from(packet, 0)
            if magic != FRAME_HEADER_MAGIC or ptype != LIDAR_POINT_DATA_PACKET_TYPE:
                continue
            body = packet[FRAME_HEADER_SIZE:-FRAME_TAIL_SIZE]
            if len(body) < POINT_DATA_SIZE:
                continue
            pts = parse_point_cloud(body)
            now = time.time()
            with self._lock:
                self._chunks.append((now, pts))
                cutoff = now - self.keep_seconds
                while self._chunks and self._chunks[0][0] < cutoff:
                    self._chunks.popleft()
            self.packets_received += 1
            self.points_received += len(pts)
            self.last_packet_time = now

    def snapshot(self, window=None, t_end=None):
        """(N,4) [x,y,z,intensity] array of points received in [t_end-window, t_end]."""
        w = self.window_seconds if window is None else window
        t1 = time.time() if t_end is None else t_end
        with self._lock:
            arrays = [a for t, a in self._chunks if t1 - w <= t <= t1]
        return np.concatenate(arrays, axis=0) if arrays else np.empty((0, 4))

    def alive(self, within=1.0):
        return (time.time() - self.last_packet_time) < within
