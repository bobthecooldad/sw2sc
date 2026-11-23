# Survey 0.15.0 (2026-11-19)

Same parts as 0.14.0 rebuild and match (13 of 199 parts read: 107 not fully decoded, 71
imported bodies, 5 rebuilt without a match, 3 older streams not numbered). Constraints in the
13: 121 (was 93), with 11 construction lines. Part K: sketch at 0 degrees of
freedom (`sketch.inspect`), D4 = 5 grows it to 160 x 60 about the origin. Unit tests: 49 run,
OK (25 skipped where samples are not reachable from the worktree).

Degrees of freedom left per sketch (headless `sketch.inspect`; all solve, none failing):
0 for Part K, PCB_v1 and Valve slide Bar's Sketch1; 4 to 8 for the pins, shafts,
bars and the load-cell spacer; Part T9 21 and 73, drive belt 21, Valve slide Bar's Sketch2 28.
What's left is mostly relations to projected geometry (the origin, axes, model edges) and
dimensions not decoded yet (angles, point to line).
