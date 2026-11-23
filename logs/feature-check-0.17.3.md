# Feature check 0.17.3 (samples/slippad-solidworks)

- kernel: solidcraft-cli 0.47.0 at C:\dev\solidcraft\target\release\solidcraft-cli.exe (checkout C:\dev\solidcraft, commit 1f8df8628 of 2026-11-23 09:46)
- feature stream not numbered (pre-2015): 2
- not fully decoded: 4
- rebuilt, does not match: 19
- rebuilt, matches the solid: 10

| Part | Result | Notes |
|---|---|---|
| Base_loadCell_v1.SLDPRT | mismatch | no build to compare |
| FrameBracket_v2.SLDPRT | mismatch | no build to compare |
| FrameBracket_v2_loadCell_v1.SLDPRT | mismatch | no build to compare |
| GT2_Bobbin_Idler_v2.SLDPRT | not fully decoded | Imported1: imported body among features |
| GT2_Bobbin_v2.SLDPRT | not fully decoded | D2: moEndSpec_c not converted yet |
| GT2_Spur_v2_18tooth.SLDPRT | not fully decoded | Imported1: imported body among features |
| MicroGearMotor_v1.SLDPRT | mismatch | no build to compare |
| PCB_v1.SLDPRT | rebuilt | Boss-Extrude1 negative |
| PET_tape_top_v1.SLDPRT | mismatch | too much material (+22955.7%): a loop is an island, or a cut didn't take |
| PET_tape_v1.SLDPRT | mismatch | too much material (+31748.8%): a loop is an island, or a cut didn't take |
| Spring_0_5len_0_24dia_1986K630.SLDPRT | pre-2015 |  |
| Top_beltSupportRim_v1.SLDPRT | rebuilt | Boss-Extrude1 negative, Cut-Extrude1 negative, Cut-Extrude2 negative, Cut-Extrude5 negative, Cut-Extrude6 negative |
| Top_mainplate_v1.SLDPRT | mismatch | no build to compare |
| Top_modular_aperture_v2.SLDPRT | rebuilt | Boss-Extrude1 negative, Cut-Extrude1 negative, Cut-Extrude2 negative |
| arm_idler_single_v3_mirrored.SLDPRT | not fully decoded | arm_idler_single_v4_Mirrored: moMirrorStock_c not converted yet |
| arm_idler_single_v4.SLDPRT | mismatch | no build to compare |
| arm_idler_v2.SLDPRT | rebuilt | Boss-Extrude1 symmetric, Cut-Extrude1 symmetric |
| bearing_3x6x2.SLDPRT | rebuilt | Revolve1 360.0 |
| drive_belt_71mm_v1.SLDPRT | rebuilt | Boss-Extrude1 positive |
| finger_aperture_15mm_v4.SLDPRT | mismatch | too little material (-0.7%): a feature is missing, or its direction is wrong |
| idler_differential_arm_short_v1.SLDPRT | mismatch | no build to compare |
| idler_differential_arm_v1.SLDPRT | mismatch | no build to compare |
| idler_differential_baseJoint_v1.SLDPRT | mismatch | too little material (-59.3%): a feature is missing, or its direction is wrong |
| idler_single_v1.SLDPRT | mismatch | too much material (+12.2%): a loop is an island, or a cut didn't take |
| idler_single_v2.SLDPRT | rebuilt | Revolve1 360.0, Cut-Extrude1 symmetric |
| loadCell_v1.SLDPRT | mismatch | no build to compare |
| loadcell_centerPlatform_v1.SLDPRT | mismatch | no build to compare |
| loadcell_spacer_v1.SLDPRT | rebuilt | Boss-Extrude1 negative |
| motorClip_v1.SLDPRT | mismatch | no build to compare |
| setScrew_M2x2_5_92015A207.SLDPRT | pre-2015 |  |
| shaft_3x22mm.SLDPRT | rebuilt | Boss-Extrude1 negative |
| shaft_3x55mm.SLDPRT | rebuilt | Boss-Extrude1 symmetric |
| spring_base_tab_v1.SLDPRT | mismatch | too little material (-7.1%): a feature is missing, or its direction is wrong |
| spring_base_v1.SLDPRT | mismatch | no build to compare |
| spring_holder_v1.SLDPRT | mismatch | no build to compare |
