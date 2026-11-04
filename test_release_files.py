"""The release workflow must put the folders the program reads at run time into the app folder (0.8.3 shipped without assets/, so the start-up
card had no logo and no Lora font)."""
import os, re
HERE = os.path.dirname(os.path.abspath(__file__))
wf = open(os.path.join(HERE, ".github", "workflows", "release.yml"), encoding="utf-8").read()
import splash
need = {"assets"}                      # folders under the program folder that splash.py / the icons read
assert os.path.isfile(os.path.join(HERE, "assets", "openpara-logo.svg")) and os.path.isfile(os.path.join(HERE, "assets", "fonts", "Lora-Variable.ttf"))
for d in need:
    assert re.search(r'Copy-Item %s -Destination "\$app\\%s"' % (d, d), wf), f"release.yml does not copy {d}/ into the app"
assert splash.asset("openpara-logo.svg").startswith(HERE)
print("release files ok")
