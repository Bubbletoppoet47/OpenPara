#!/bin/bash
# One-time setup for the Raspberry Pi (Pi 5, 64-bit Raspberry Pi OS). Run:  bash app/setup_pi.sh   (or SETUP on the start screen)
# Needs internet for the package install (use Wi-Fi - the Ethernet port is reserved for the LiDAR).
set -e
echo "== Installing packages =="
sudo apt update
sudo apt install -y python3-opencv python3-numpy python3-scipy python3-tk python3-pip

# onnxruntime runs your trained model (no PyTorch needed on the Pi)
pip3 install --break-system-packages onnxruntime || pip3 install onnxruntime

echo "== LiDAR network (Ethernet port -> 192.168.1.2) =="
# The L2 is at 192.168.1.62 and streams to 192.168.1.2:6201. This adds a wired profile with that
# fixed address; it does not touch Wi-Fi.
sudo nmcli connection delete lidar 2>/dev/null || true
sudo nmcli connection add type ethernet ifname eth0 con-name lidar \
     ipv4.method manual ipv4.addresses 192.168.1.2/24 ipv6.method ignore
sudo nmcli connection up lidar || echo "(Will come up when the LiDAR cable is plugged in)"

echo "== Checking =="
python3 - <<'PY'
import cv2, numpy, scipy
print("OpenCV", cv2.__version__, "| numpy", numpy.__version__, "| scipy", scipy.__version__)
print("aruco:", hasattr(cv2, "aruco"))
try:
    import onnxruntime; print("onnxruntime", onnxruntime.__version__)
except ImportError:
    print("onnxruntime NOT installed (needed only for gimble_detect.py)")
PY
# the start screen on the Pi's desktop, so nothing has to be looked for on the drive
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -d "$HOME/Desktop" ] && [ -f "$ROOT/Gimble.desktop" ]; then
    cp "$ROOT/Gimble.desktop" "$HOME/Desktop/Gimble.desktop" && chmod +x "$HOME/Desktop/Gimble.desktop" && echo "Put 'Gimble' on the desktop."
fi
echo "Done. Start with a double-click on Gimble (on the desktop, or on the drive)."
