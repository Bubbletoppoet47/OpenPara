import subprocess, time, resource, os, sys, shlex
SCR="/tmp/claude-0/-home-claude/185fe3ec-3984-59f4-ac61-89b69f00ea6d/scratchpad/orca_trial"
ORCA="/home/claude/orcaslicer/orcaslicer"
D=ORCA+"/deps_src"
inc=[ORCA+"/src",D,ORCA+"/src/libslic3r",SCR+"/gen",D+"/clipper2/Clipper2Lib/include",D+"/admesh",D+"/libigl",D+"/libnest2d",D+"/agg",D+"/ankerl",D+"/earcut",D+"/fast_float",D+"/glu-libtess",D+"/miniz",D+"/nanosvg",D+"/nlohmann",D+"/qhull",D+"/qoi",D+"/semver",D+"/stb_dxt",D+"/mcut",D+"/Shiny",D+"/hints",D+"/clipper2"]
flags=["-std=c++17","-O1","-w","-DBOOST_ALL_NO_LIB","-DBOOST_LOG_DYN_LINK","-DTBB_PREVIEW_GLOBAL_CONTROL"]
files=sys.argv[1:]
os.makedirs(SCR+"/obj",exist_ok=True)
for f in files:
    out=SCR+"/obj/"+f.replace("/","_")+".o"
    cmd=["g++"]+flags+[x for i in inc for x in ("-I",i)]+["-isystem","/usr/include/eigen3","-c",f,"-o",out]
    t=time.time(); before=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    p=subprocess.run(cmd,cwd=ORCA+"/src/libslic3r",capture_output=True,text=True)
    dt=time.time()-t; mx=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss/1024
    errs=[l for l in p.stderr.splitlines() if "error" in l]
    print(f"{f:32s} rc={p.returncode} {dt:6.1f}s  peak(max so far)={mx:6.0f}MB  errors={len(errs)}",flush=True)
    for l in errs[:3]: print("     ",l[:230],flush=True)
print("DONE")
