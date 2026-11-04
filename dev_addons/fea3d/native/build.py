"""Builds the native library: python build.py [linux|windows]  (a compiler is only needed for this; users get the finished cfea.so / cfea.dll).
Linux: gcc -O3 -fopenmp.  Windows: the DLL is cross-built with MinGW, single-threaded on purpose (a statically linked OpenMP runtime can crash when the calling thread exits)
and with its runtime linked statically so it runs without extra DLLs."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def build(target):
    src = os.path.join(HERE, "cfea.c")
    if target == "windows":
        cmd = ["x86_64-w64-mingw32-gcc", "-O3", "-shared", "-static", "-o", os.path.join(HERE, "cfea.dll"), src, "-lm"]
    else:
        cmd = ["gcc", "-O3", "-fopenmp", "-shared", "-fPIC", "-o", os.path.join(HERE, "cfea.so"), src, "-lm"]
    print(" ".join(cmd))
    subprocess.check_call(cmd)


if __name__ == "__main__":
    for t in (sys.argv[1:] or ["linux"]):
        build(t)
