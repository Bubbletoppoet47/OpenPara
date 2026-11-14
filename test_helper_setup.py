"""The set-up files that "Get the helper" saves next to openpara_remote_helper.py: they install Python on the other computer when it has none.

The Linux script is run for real here against stand-ins for python3, sudo, id and each package manager (no network, nothing installed):
Python there / missing / too old, root or sudo or neither, every package manager, answering the question or not, and the double-click
launcher.  The Windows .bat cannot run here (no cmd.exe), so it is checked for what goes wrong in batch files: the labels every goto and
call needs, quotes, characters cmd.exe treats as commands inside echo lines, the download address and the installer arguments.
"""
import os, re, shlex, shutil, stat, subprocess, sys, tempfile, time
if os.name == "nt":
    print("skipped: the Linux script needs bash and a terminal")
    sys.exit(0)
import pty, select

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "addons_src", "remote", "helper_setup")
BASH = shutil.which("bash")
T = tempfile.mkdtemp(prefix="opara_setup_")
LINK_TOOLS = ("bash", "dirname", "sh", "cp", "chmod", "find", "head")      # what the script (and the launcher line) call besides the stand-ins


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


def python_stub(minor):
    """A python3 that says it is 3.<minor>: the check the script sends it with -c is run by the real interpreter against that version."""
    return ("#!/bin/sh\n"
            f"MINOR={minor}\n"
            f'if [ "$1" = "-c" ]; then exec "{sys.executable}" -c "import sys; sys.version_info = (3, $MINOR, 0, \'final\', 0)\n$2"; fi\n'
            'if [ "$1" = "-V" ]; then echo "Python 3.$MINOR.0"; exit 0; fi\n'
            'echo "PYTHON $0 $*" >> "$LOG"\n'
            "exit 0\n")


class Box:
    """A computer: a folder of programs (the only PATH), the helper folder with the set-up script, and a log of what was run."""
    n = 0

    def __init__(self, python=None, pm=None, sudo=True, uid=1000, installs=11, need_sudo_password=False):
        Box.n += 1
        self.root = os.path.join(T, f"box{Box.n}")
        self.bin = os.path.join(self.root, "bin")
        self.folder = os.path.join(self.root, "usb", "OpenPara Remote helper")        # spaces, as on the real drive
        os.makedirs(self.bin); os.makedirs(self.folder)
        self.log = os.path.join(self.root, "log.txt")
        open(self.log, "w").close()
        for tool in LINK_TOOLS:
            os.symlink(shutil.which(tool), os.path.join(self.bin, tool))
        self.uid = uid
        write_exec(os.path.join(self.bin, "id"), '#!/bin/sh\necho "$FAKE_UID"\n')
        self.stub_installed = os.path.join(self.root, "python_installed")             # what the package manager puts in bin/python3
        write_exec(self.stub_installed, python_stub(installs))
        if python is not None:
            write_exec(os.path.join(self.bin, "python3"), python_stub(python))
        if sudo:
            write_exec(os.path.join(self.bin, "sudo"), '#!/bin/sh\necho "SUDO $*" >> "$LOG"\nexec "$@"\n')
        for name in ((pm,) if isinstance(pm, str) else (pm or ())):
            write_exec(os.path.join(self.bin, name),
                       "#!/bin/sh\n"
                       f'echo "{name} $*" >> "$LOG"\n'
                       'case "$*" in *python*) cp "$STUB_INSTALLED" "$BIN/python3"; chmod +x "$BIN/python3";; esac\n'
                       "exit 0\n")
        shutil.copy(os.path.join(SRC, "setup_linux.sh"), os.path.join(self.folder, "Set up (Linux).sh"))
        shutil.copy(os.path.join(SRC, "setup_linux.desktop"), os.path.join(self.folder, "Set up (Raspberry Pi, Linux).desktop"))
        open(os.path.join(self.folder, "openpara_remote_helper.py"), "w").write("# stand-in for the helper\n")

    def env(self):
        return {"PATH": self.bin, "LOG": self.log, "BIN": self.bin, "STUB_INSTALLED": self.stub_installed, "FAKE_UID": str(self.uid),
                "HOME": os.path.join(self.root, "home"), "LC_ALL": "C"}

    def run(self, *args, timeout=60):
        p = subprocess.run([BASH, os.path.join(self.folder, "Set up (Linux).sh"), *args], env=self.env(), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, text=True)
        return p.returncode, p.stdout

    def run_tty(self, typed, *args, timeout=60):
        """Runs the script on a terminal and types `typed` to it."""
        master, slave = pty.openpty()
        p = subprocess.Popen([BASH, os.path.join(self.folder, "Set up (Linux).sh"), *args], env=self.env(), stdin=slave, stdout=slave,
                             stderr=slave, close_fds=True)
        os.close(slave)
        os.write(master, typed.encode())
        out = b""
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([master], [], [], 0.2)
            if r:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
            elif p.poll() is not None:
                break
        p.wait(timeout=10)
        os.close(master)
        return p.returncode, out.decode(errors="replace").replace("\r\n", "\n")

    def calls(self):
        return [l.rstrip("\n") for l in open(self.log)]

    def helper_calls(self):
        return [c for c in self.calls() if c.startswith("PYTHON ")]


def helper_run_ok(box):
    h = box.helper_calls()
    return len(h) == 1 and h[0].endswith("openpara_remote_helper.py --install")


# ---- Python 3.8 or newer is there: nothing is installed, the helper's own set-up runs
b = Box(python=11, pm="apt-get")
rc, out = b.run()
assert rc == 0 and helper_run_ok(b), (rc, out, b.calls())
assert not any(c.startswith(("SUDO", "apt-get")) for c in b.calls()), b.calls()
assert "Using" in out and "ACCESS CODE" in out and "Python 3.11.0" in out, out
b = Box(python=8, pm="apt-get")                                                   # 3.8 is enough
assert b.run()[0] == 0 and helper_run_ok(b)
b = Box(python=11, pm="apt-get")                                                  # no --yes needed when nothing has to be asked
assert b.run()[0] == 0 and helper_run_ok(b)
rc, out = Box(python=11).run("--yes")
assert rc == 0, out
for name in ("python", "python3.12"):                                              # also found under another name
    b = Box(pm="apt-get"); write_exec(os.path.join(b.bin, name), python_stub(12))
    assert b.run()[0] == 0 and helper_run_ok(b) and not any(c.startswith("apt-get") for c in b.calls()), name

# ---- Python is missing: installed with the package manager (sudo for a normal user, directly for root), then the helper is set up
b = Box(pm="apt-get")
rc, out = b.run("--yes")
assert rc == 0 and helper_run_ok(b), (rc, out, b.calls())
assert b.calls()[0] == "SUDO sh -c apt-get update; apt-get install -y python3", b.calls()
assert [c for c in b.calls() if c.startswith("apt-get")] == ["apt-get update", "apt-get install -y python3"], b.calls()
assert "Python 3.8 or newer was not found" in out and "sudo sh -c 'apt-get update; apt-get install -y python3'" in out, out
b = Box(pm="apt-get", uid=0, sudo=False)                                          # root: no sudo needed (or present)
rc, out = b.run("--yes")
assert rc == 0 and helper_run_ok(b) and not any(c.startswith("SUDO") for c in b.calls()), (rc, out, b.calls())
b = Box(pm="apt-get", uid=0)                                                      # root does not use sudo even when it exists
assert b.run("-y")[0] == 0 and not any(c.startswith("SUDO") for c in b.calls())
for pm, line in (("dnf", "dnf install -y python3"), ("yum", "yum install -y python3"), ("zypper", "zypper --non-interactive install python3"),
                 ("pacman", "pacman -S --needed --noconfirm python"), ("apk", "apk add python3")):
    b = Box(pm=pm)
    rc, out = b.run("--yes")
    assert rc == 0 and helper_run_ok(b), (pm, rc, out, b.calls())
    assert b.calls()[0] == f"SUDO sh -c {line}" and b.calls()[1] == line, (pm, b.calls())
b = Box(pm=("yum", "dnf"))                                                         # the first one this script knows is used
b.run("--yes"); assert any(c.startswith("dnf ") for c in b.calls()) and not any(c.startswith("yum ") for c in b.calls()), b.calls()

# ---- Python is there but too old: it counts as missing
b = Box(python=5, pm="apt-get", installs=11)                                       # the install brings a new one
rc, out = b.run("--yes")
assert rc == 0 and helper_run_ok(b) and "apt-get install -y python3" in " ".join(b.calls()), (rc, out, b.calls())
b = Box(python=5, pm="apt-get", installs=5)                                        # the system has nothing newer to give
rc, out = b.run("--yes")
assert rc == 1 and not b.helper_calls() and "still not here" in out and "Python 3.5.0" in out and "too old" in out, (rc, out)

# ---- nothing can be installed: said so, with what to do by hand, and the helper is not run
b = Box(pm=None)
rc, out = b.run("--yes")
assert rc == 1 and not b.helper_calls() and "no package manager" in out and "by hand" in out, (rc, out)
b = Box(pm="apt-get", sudo=False)                                                  # not root and no sudo
rc, out = b.run("--yes")
assert rc == 1 and not b.helper_calls() and "no sudo" in out and "sh -c 'apt-get update; apt-get install -y python3'" in out, (rc, out)
assert not any(c.startswith("apt-get") for c in b.calls())
b = Box(python=11); os.remove(os.path.join(b.folder, "openpara_remote_helper.py"))   # the helper file did not come along
rc, out = b.run("--yes")
assert rc == 1 and "openpara_remote_helper.py is not in this folder" in out and not b.helper_calls(), (rc, out)
b = Box(pm="apt-get")                                                              # the install itself fails (offline ...): still no helper
write_exec(os.path.join(b.bin, "apt-get"), '#!/bin/sh\necho "apt-get $*" >> "$LOG"\nexit 100\n')
rc, out = b.run("--yes")
assert rc == 1 and not b.helper_calls() and "still not here" in out, (rc, out)

# ---- the question: without --yes and without anybody to ask nothing is installed; on a terminal the answer decides
b = Box(pm="apt-get")
rc, out = b.run()
assert rc == 1 and "nobody to ask" in out and not b.helper_calls() and not any(c.startswith(("SUDO", "apt-get")) for c in b.calls()), (rc, out)
b = Box(pm="apt-get")
rc, out = b.run_tty("n\n\n")
assert rc == 1 and "Install Python now? [Y/n]" in out and "was not installed" in out, (rc, out)
assert not b.helper_calls() and not any(c.startswith(("SUDO", "apt-get")) for c in b.calls()), b.calls()
b = Box(pm="apt-get")
rc, out = b.run_tty("\n\n")                                                        # Enter = yes
assert rc == 0 and helper_run_ok(b) and any(c.startswith("apt-get install") for c in b.calls()), (rc, out, b.calls())
assert "Press Enter to close." in out, out
b = Box(pm="apt-get")
rc, out = b.run_tty("yes\n\n")
assert rc == 0 and helper_run_ok(b), (rc, out)
b = Box(pm="apt-get")
rc, out = b.run_tty("no thanks\n\n")
assert rc == 1 and not b.helper_calls(), (rc, out)

# ---- the double-click launcher finds the script on a drive (here: under HOME) and runs it; without the files it says so
b = Box(python=11)
exec_line = next(l for l in open(os.path.join(b.folder, "Set up (Raspberry Pi, Linux).desktop")) if l.startswith("Exec=")).strip()[5:]
argv = shlex.split(exec_line)
assert argv[:2] == ["bash", "-c"] and "Set up (Linux).sh" in argv[2], argv
os.makedirs(b.env()["HOME"]); shutil.move(os.path.join(b.root, "usb"), os.path.join(b.env()["HOME"], "usb"))
p = subprocess.run([BASH, "-c", argv[2]], env=b.env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
assert p.returncode == 0 and helper_run_ok(b), (p.returncode, p.stdout, b.calls())
shutil.rmtree(os.path.join(b.env()["HOME"], "usb"))
p = subprocess.run([BASH, "-c", argv[2]], env=b.env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
assert "were not found on any drive" in p.stdout, p.stdout
desk = open(os.path.join(SRC, "setup_linux.desktop")).read()
assert "Terminal=true" in desk and "\r" not in desk and desk.startswith("[Desktop Entry]\n")

# ---- the shell script itself is well formed
assert subprocess.run([BASH, "-n", os.path.join(SRC, "setup_linux.sh")]).returncode == 0
sh_text = open(os.path.join(SRC, "setup_linux.sh"), newline="").read()
assert "\r" not in sh_text and sh_text.startswith("#!/bin/bash\n")

# ---- the Windows .bat: everything cmd.exe is picky about
raw = open(os.path.join(SRC, "setup_windows.bat"), "rb").read()
text = raw.decode("ascii")                                                         # plain ASCII only (the file is written as ASCII)
text = text.replace("\r\n", "\n")
lines = text.split("\n")
assert lines[0] == "@echo off" and "\r" not in text
labels = {}
for i, l in enumerate(lines):
    m = re.match(r"^:(\w+)\s*$", l)
    if m:
        assert m.group(1) not in labels, f"label {m.group(1)} twice"
        labels[m.group(1)] = i
targets = set()
for l in lines:
    if re.match(r"^\s*rem\b", l, re.I):
        continue
    for m in re.finditer(r"\bgoto\s+:?(\w+)", l, re.I):
        targets.add(m.group(1))
    for m in re.finditer(r"\bcall\s+:(\w+)", l, re.I):
        targets.add(m.group(1))
targets.discard("eof")
assert targets <= set(labels), f"a goto or call without its label: {sorted(targets - set(labels))}"
assert set(labels) <= targets | {"findpython", "try", "tryfile"}, f"a label nobody uses: {sorted(set(labels) - targets)}"
for i, l in enumerate(lines):
    assert l.count('"') % 2 == 0, f"line {i + 1}: odd number of quotes: {l}"
    assert not l.rstrip().endswith("(") and not l.lstrip().startswith(")"), f"line {i + 1}: a block (brackets in echo lines would break it)"
    assert len(l) < 250, f"line {i + 1} is long"
    if re.match(r"^\s*echo\b", l, re.I) or re.match(r"^\s*if\b.*\becho\b", l, re.I):
        body = re.sub(r"%\w+%", "", l)                                             # a variable is fine; any other %, & | < > ^ is a command to cmd
        assert not re.search(r"[&|<>^%]", body), f"line {i + 1}: a character cmd.exe would act on: {l}"
    for var in re.findall(r"%(\w+)%", l):
        assert var in {"ASSUME_YES", "RC", "INSTALL_RC", "PYEXE", "PYURL", "PYDL", "PYFILE", "ARCH", "TEMP", "PROCESSOR_ARCHITECTURE",
                       "PROCESSOR_ARCHITEW6432", "LOCALAPPDATA", "ProgramFiles", "ProgramW6432", "errorlevel"}, f"line {i + 1}: {var}"
# a subroutine does not run into the next label: every one ends with exit /b, and the main part ends at :end with exit /b
for name in ("findpython", "try", "tryfile"):
    body = [x for x in lines[labels[name] + 1:] if x.strip()]
    stop = next((k for k, x in enumerate(body) if x.startswith(":")), len(body))
    assert body[stop - 1].strip() == "exit /b 0", name
end = lines[labels["end"] + 1:labels["findpython"]]
assert "exit /b %RC%" in end
# what it does
assert "python-3.12.10-amd64.exe" in text and "python-3.12.10-arm64.exe" in text and 'PYFILE=python-3.12.10.exe' in text
assert "https://www.python.org/ftp/python/3.12.10/%PYFILE%" in text
assert 'start "" /wait "%PYDL%" /quiet InstallAllUsers=0 PrependPath=1' in text        # waits for the installer; per user, no administrator
assert "Get-AuthenticodeSignature" in text and "Python Software Foundation" in text and "Tls12" in text
assert text.index("Get-AuthenticodeSignature") < text.index("/quiet"), "the file is checked before it is run"
assert "choice /c YN" in text and '"--yes"' in text and 'if "%ASSUME_YES%"=="0" pause' in text
assert '"%PYEXE%" openpara_remote_helper.py --install' in text
for cand in ('"py -3"', '"python"', "Programs\\Python\\Python%%V"):
    assert cand in text, cand
# the same Python test as the Linux script's, written for cmd
assert text.count("sys.version_info >= (3, 8)") == 2

print("ok")
sys.stdout.flush()
shutil.rmtree(T, ignore_errors=True)
