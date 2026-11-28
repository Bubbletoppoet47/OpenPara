// nanosvg is a header-only library whose implementation is compiled into exactly one source file of a program. In Orca Slicer that file is a
// window (GUI/BitmapCache.cpp), which orca_core does not build, and libslic3r/NSVGUtils.cpp needs the functions. This file is ours.
#define NANOSVG_IMPLEMENTATION
#include <nanosvg/nanosvg.h>
#define NANOSVGRAST_IMPLEMENTATION
#include <nanosvg/nanosvgrast.h>
