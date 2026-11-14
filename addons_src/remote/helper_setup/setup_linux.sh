#!/bin/bash
# OpenPara Remote helper - set-up for Linux and the Raspberry Pi.
#
# Finds Python 3.8 or newer (and installs it first when this computer has none), then runs the helper's own set-up,
# which shows the ACCESS CODE and makes the helper start with every login.
#
#   bash "Set up (Linux).sh"           asks before it installs anything
#   bash "Set up (Linux).sh" --yes     does not ask

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
    esac
done

# Leave: keeps a terminal window open (when somebody is looking at it) so that what was written can be read.
quit() {
    echo
    if [ "$ASSUME_YES" = "0" ] && [ -t 0 ]; then
        read -r -p "Press Enter to close. " _
    fi
    exit "$1"
}

# Asks a yes/no question; yes by default.  Without a person to ask (or --yes) the answer is given by --yes alone.
ask() {
    [ "$ASSUME_YES" = "1" ] && return 0
    if [ ! -t 0 ]; then
        echo "(There is nobody to ask here: run this again in a terminal, or add --yes.)"
        return 1
    fi
    read -r -p "$1 [Y/n] " answer
    case "$answer" in
        ""|[Yy]|[Yy][Ee][Ss]) return 0 ;;
        *) return 1 ;;
    esac
}

# Sets PY to the first Python 3.8 or newer on this computer.
find_python() {
    PY=""
    local name path
    for name in python3 python python3.13 python3.12 python3.11 python3.10 python3.9 python3.8; do
        path="$(command -v "$name" 2>/dev/null)" || continue
        if "$path" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
            PY="$path"
            return 0
        fi
    done
    return 1
}

# Sets INSTALL_CMD to what installs Python with this computer's package manager.
pick_installer() {
    if command -v apt-get >/dev/null 2>&1; then
        INSTALL_CMD="apt-get update; apt-get install -y python3"
    elif command -v dnf >/dev/null 2>&1; then
        INSTALL_CMD="dnf install -y python3"
    elif command -v yum >/dev/null 2>&1; then
        INSTALL_CMD="yum install -y python3"
    elif command -v zypper >/dev/null 2>&1; then
        INSTALL_CMD="zypper --non-interactive install python3"
    elif command -v pacman >/dev/null 2>&1; then
        INSTALL_CMD="pacman -S --needed --noconfirm python"
    elif command -v apk >/dev/null 2>&1; then
        INSTALL_CMD="apk add python3"
    else
        return 1
    fi
}

cd "$here" || quit 1
if [ ! -f openpara_remote_helper.py ]; then
    echo "openpara_remote_helper.py is not in this folder ($here)."
    echo "Copy the whole \"OpenPara Remote helper\" folder to this computer, then run this again."
    quit 1
fi

if ! find_python; then
    echo "Python 3.8 or newer was not found on this computer."
    echo
    if ! pick_installer; then
        echo "This computer has no package manager that this set-up knows (apt, dnf, yum, zypper, pacman, apk)."
        echo "Install Python 3.8 or newer by hand, then run this again."
        quit 1
    fi
    if [ "$(id -u)" = "0" ]; then
        AS_ROOT=()
    elif command -v sudo >/dev/null 2>&1; then
        AS_ROOT=(sudo)
    else
        echo "Python has to be installed with administrator rights, and this computer has no sudo."
        echo "Log in as the administrator (root) and run:"
        echo "    sh -c '$INSTALL_CMD'"
        echo "then run this again."
        quit 1
    fi
    echo "OpenPara can install it for you with:"
    echo "    ${AS_ROOT[*]} sh -c '$INSTALL_CMD'"
    echo
    if ! ask "Install Python now?"; then
        echo "Python was not installed, so the helper was not set up."
        quit 1
    fi
    echo
    "${AS_ROOT[@]}" sh -c "$INSTALL_CMD"
    echo
    if ! find_python; then
        echo "Python 3.8 or newer is still not here after the install."
        old="$(command -v python3 2>/dev/null)"
        if [ -n "$old" ]; then
            echo "This computer has $("$old" -V 2>&1), which is older than the helper needs: its system is probably too old."
        fi
        quit 1
    fi
fi

echo "Using $PY ($("$PY" -V 2>&1))"
echo
"$PY" openpara_remote_helper.py --install
status=$?
echo
if [ "$status" = "0" ]; then
    echo "Write the ACCESS CODE down (it is shown once), then restart this computer."
else
    echo "The helper's own set-up reported a problem (code $status); what it wrote above says what."
fi
quit "$status"
