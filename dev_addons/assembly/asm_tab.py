"""asm_tab.py - the playground's Assembly tab: OpenPara's own assembly window (core/assembly.py), so components, mates, patterns, configurations
and sub-assemblies behave as in OpenPara.  The playground app is its `shell`: it finds open part tabs, opens parts for Edit Component and reads
their live documents."""
import os


def make_tab(host=None, path=None):
    import assembly
    p = path if path and path.lower().endswith(".gpa") else None
    w = assembly.AssemblyWindow(path=p, shell=host)
    return w
