#!/bin/bash
# one fresh python per file so the peak-memory figure belongs to that file alone
S=/tmp/claude-0/-home-claude/185fe3ec-3984-59f4-ac61-89b69f00ea6d/scratchpad/orca_trial
cd $S
echo "# compile probe $(date -u +%FT%TZ)  g++ $(g++ -dumpversion) -O1, 2 cores, Orca 1044ef4407d7" > probe_final.log
for f in PrintObjectSlice.cpp PerimeterGenerator.cpp PrintConfig.cpp Support/TreeSupport3D.cpp Arachne/WallToolPaths.cpp; do python3 trial.py $f | grep -v DONE >> probe_final.log; done
for f in Print.cpp GCode.cpp Model.cpp; do python3 trial_ovl.py $f | grep -v DONE >> probe_final.log; done
for f in MeshBoolean.cpp CutSurface.cpp; do python3 trial_cgal.py $f | grep -v DONE >> probe_final.log; done
echo FINISHED >> probe_final.log
