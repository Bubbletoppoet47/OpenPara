#!/bin/bash
# Starts the Gimble start screen from wherever this folder is (USB drive or internal disk).  Options are passed on (--windowed ...).
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP/.." || exit 1
mkdir -p logs
python3 "$APP/gimble_menu.py" "$@" 2>>logs/gimble_log.txt
