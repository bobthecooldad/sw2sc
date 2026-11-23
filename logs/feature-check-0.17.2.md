# Feature check 0.17.2 (samples/slippad-solidworks)

- kernel: solidcraft-cli 0.47.0 at C:\dev\solidcraft\target\release\solidcraft-cli.exe (checkout C:\dev\solidcraft, commit 1f8df8628 of 2026-11-23 09:46)
- rebuilt, does not match: 19
- rebuilt, matches the solid: 10
- not fully decoded: 4
- feature stream not numbered (pre-2015): 2

| Part | Result | Notes |
|---|---|---|
| Base_loadCell_v1.SLDPRT | mismatch |  |
| FrameBracket_v2.SLDPRT | mismatch |  |
| FrameBracket_v2_loadCell_v1.SLDPRT | mismatch |  |
| GT2_Bobbin_Idler_v2.SLDPRT | not fully decoded | Imported1: imported body among features |
| GT2_Bobbin_v2.SLDPRT | not fully decoded | D2: moEndSpec_c not converted yet |
| GT2_Spur_v2_18tooth.SLDPRT | not fully decoded | Imported1: imported body among features |
| MicroGearMotor_v1.SLDPRT | mismatch |  |
| PCB_v1.SLDPRT | rebuilt | Boss-Extrude1 negative |
| PET_tape_top_v1.SLDPRT | mismatch |  |
| PET_tape_v1.SLDPRT | mismatch |  |
| Spring_0_5len_0_24dia_1986K630.SLDPRT | pre-2015 |  |
| Top_beltSupportRim_v1.SLDPRT | rebuilt | Boss-Extrude1 negative, Cut-Extrude1 negative, Cut-Extrude2 negative, Cut-Extrude5 negative, Cut-Extrude6 negative |
| Top_mainplate_v1.SLDPRT | mismatch |  |
| Top_modular_aperture_v2.SLDPRT | rebuilt | Boss-Extrude1 negative, Cut-Extrude1 negative, Cut-Extrude2 negative |
| arm_idler_single_v3_mirrored.SLDPRT | not fully decoded | arm_idler_single_v4_Mirrored: moMirrorStock_c not converted yet |
| arm_idler_single_v4.SLDPRT | mismatch |  |
| arm_idler_v2.SLDPRT | rebuilt | Boss-Extrude1 symmetric, Cut-Extrude1 symmetric |
| bearing_3x6x2.SLDPRT | rebuilt | Revolve1 360.0 |
| drive_belt_71mm_v1.SLDPRT | rebuilt | Boss-Extrude1 positive |
| finger_aperture_15mm_v4.SLDPRT | mismatch |  |
| idler_differential_arm_short_v1.SLDPRT | mismatch |  |
| idler_differential_arm_v1.SLDPRT | mismatch |  |
| idler_differential_baseJoint_v1.SLDPRT | mismatch |  |
| idler_single_v1.SLDPRT | mismatch |  |
| idler_single_v2.SLDPRT | rebuilt | Revolve1 360.0, Cut-Extrude1 symmetric |
| loadCell_v1.SLDPRT | mismatch |  |
| loadcell_centerPlatform_v1.SLDPRT | mismatch |  |
| loadcell_spacer_v1.SLDPRT | rebuilt | Boss-Extrude1 negative |
| motorClip_v1.SLDPRT | mismatch |  |
| setScrew_M2x2_5_92015A207.SLDPRT | pre-2015 |  |
| shaft_3x22mm.SLDPRT | rebuilt | Boss-Extrude1 negative |
| shaft_3x55mm.SLDPRT | rebuilt | Boss-Extrude1 symmetric |
| spring_base_tab_v1.SLDPRT | mismatch |  |
| spring_base_v1.SLDPRT | mismatch |  |
| spring_holder_v1.SLDPRT | mismatch |  |
