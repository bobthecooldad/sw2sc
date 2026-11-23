# Survey 0.13.0 (2026-11-19)

Feature trees over the three sample sets (slippad, GrabCAD, the user's Documents), checked by rebuilding in SolidCraft 0.40.1 (`tools/feature_check.py`).

- not fully decoded: 110
- imported body (no tree in SolidWorks either): converts as import: 71
- rebuilt, matches the solid: 13
- feature stream not numbered (pre-2015): 3
- rebuilt, does not match: 2

| Part | Result | Notes |

Parts rebuilt from their feature tree and matching their solid:

- PCB_v1.SLDPRT (Boss-Extrude1 negative)
- drive_belt_71mm_v1.SLDPRT (Boss-Extrude1 positive)
- loadcell_spacer_v1.SLDPRT (Boss-Extrude1 negative)
- shaft_3x22mm.SLDPRT (Boss-Extrude1 negative)
- shaft_3x55mm.SLDPRT (Boss-Extrude1 symmetric)
- Axle Rod.SLDPRT (Boss-Extrude1 symmetric)
- Part T9.SLDPRT (Boss-Extrude1 positive, Cut-Extrude1 positive)
- 2MM Pin.SLDPRT (Boss-Extrude1 positive)
- Pin for Crank.SLDPRT (Boss-Extrude1 positive)
- Valve Operating Bar.SLDPRT (Boss-Extrude1 positive)
- Valve slide Bar.SLDPRT (Boss-Extrude1 positive, Cut-Extrude1 negative)
- Cheville bois 10x10.SLDPRT (Boss.-Extru.1 symmetric)
- Part K.SLDPRT (Boss-Extrude1 positive)

Unit tests: 48 run, OK (25 skipped where samples aren't reachable from the worktree).
