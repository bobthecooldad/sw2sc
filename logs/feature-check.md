# Feature check

- not fully decoded: 157
- imported body (no tree in SolidWorks either): converts as import: 142
- rebuilt, does not match: 23
- rebuilt, matches the solid: 23
- feature stream not numbered (pre-2015): 4

| Part | Result | Notes |
|---|---|---|
| Part C.SLDPRT | mismatch |  |
| Part L.SLDPRT | not fully decoded | Imported1: imported body among features |
| Part F.SLDPRT | not fully decoded | Boss-Extrude3: moDimText_c not converted yet; Boss-Extrude4: moDimText_c not converted yet; Boss-Extrude5: moDimText_c not converted yet; Boss-Extrude6: moDimText_c not converted yet |
| Part E.SLDPRT | not fully decoded | Sketch4: sketch text not converted yet |
| Part G.SLDPRT | not fully decoded | Scale1: moScale_c not converted yet; Sketch7<3>: no plane reference found; Sketch4: sketch text not converted yet |
| Part H.SLDPRT | not fully decoded | Sketch4: sketch text not converted yet |
| Part B.SLDPRT | not fully decoded | Cavity1: moCavity_c not converted yet; Part L<1>@Part D1: moXformStock_c not converted yet |
| Part A.SLDPRT | not fully decoded | Cavity1: moCavity_c not converted yet; Part H<2>@Part D1: moXformStock_c not converted yet |
| Part I.SLDPRT | not fully decoded | Cavity1: moCavity_c not converted yet; Part M<1>@Part D1: moXformStock_c not converted yet |
| Part M.SLDPRT | not fully decoded | Sketch2<3>: no plane reference found; Sketch2: line 4 has 1 end points; Sketch2: line 5 has 1 end points; Sketch2: line 7 has 1 end points |
| Part N.SLDPRT | not fully decoded | Mirror2: moMirrorPattern_c not converted yet |
| Part K.SLDPRT | rebuilt | Boss-Extrude1 positive |
| Adapter.SLDPRT | not fully decoded | Sketch2: no plane reference found |
| Wheel.SLDPRT | not fully decoded | Sketch1: arc 3: no centre found |
| Base_loadCell_v1.SLDPRT | not fully decoded | Cut-Extrude2: moCut_c not converted yet |
| FrameBracket_v2.SLDPRT | not fully decoded | M3x0.5 Tapped Hole1: hole's placement sketch not found; M3x0.5 Tapped Hole2: hole's placement sketch not found |
| FrameBracket_v2_loadCell_v1.SLDPRT | not fully decoded | M3x0.5 Tapped Hole1: hole's placement sketch not found; M3x0.5 Tapped Hole2: hole's placement sketch not found |
| GT2_Bobbin_Idler_v2.SLDPRT | not fully decoded | Imported1: imported body among features; Sketch3: no plane reference found; Sketch7: no plane reference found; Sketch2: arc 1: no centre found |
| GT2_Bobbin_v2.SLDPRT | not fully decoded | D2: moEndSpec_c not converted yet |
| GT2_Spur_v2_18tooth.SLDPRT | not fully decoded | Imported1: imported body among features; Sketch3: no plane reference found; Sketch7: no plane reference found; Sketch2: arc 1: no centre found |
| MicroGearMotor_v1.SLDPRT | not fully decoded | Hole Thread1: moCosmeticThread_c not converted yet; Hole Thread2: moCosmeticThread_c not converted yet; Sketch4: no plane reference found; Sketch6: no plane reference found |
| PCB_v1.SLDPRT | rebuilt | Boss-Extrude1 negative |
| PET_tape_top_v1.SLDPRT | not fully decoded | Sketch1: arc 2: no centre found; Sketch1: arc 3: no centre found; Sketch1: arc 5: no centre found |
| PET_tape_v1.SLDPRT | not fully decoded | Sketch1: arc 2: no centre found; Sketch1: arc 3: no centre found; Sketch1: arc 5: no centre found |
| Spring_0_5len_0_24dia_1986K630.SLDPRT | pre-2015 |  |
| Top_beltSupportRim_v1.SLDPRT | rebuilt | Boss-Extrude1 negative, Cut-Extrude1 negative, Cut-Extrude2 negative, Cut-Extrude5 negative, Cut-Extrude6 negative |
| Top_mainplate_v1.SLDPRT | not fully decoded | Cut-Extrude3: moCut_c not converted yet |
| Top_modular_aperture_v2.SLDPRT | not fully decoded | Cut-Extrude2: moCut_c not converted yet |
| arm_idler_single_v3_mirrored.SLDPRT | not fully decoded | arm_idler_single_v4_Mirrored: moMirrorStock_c not converted yet |
| arm_idler_single_v4.SLDPRT | not fully decoded | Sketch1: arc 3: no centre found |
| arm_idler_v2.SLDPRT | not fully decoded | Sketch1: arc 2: no centre found; Sketch1: arc 3: no centre found |
| bearing_3x6x2.SLDPRT | mismatch |  |
| drive_belt_71mm_v1.SLDPRT | rebuilt | Boss-Extrude1 positive |
| finger_aperture_15mm_v4.SLDPRT | mismatch |  |
| idler_differential_arm_short_v1.SLDPRT | mismatch |  |
| idler_differential_arm_v1.SLDPRT | mismatch |  |
| idler_differential_baseJoint_v1.SLDPRT | mismatch |  |
| idler_single_v1.SLDPRT | mismatch |  |
| idler_single_v2.SLDPRT | mismatch |  |
| loadCell_v1.SLDPRT | mismatch |  |
| loadcell_centerPlatform_v1.SLDPRT | mismatch |  |
| loadcell_spacer_v1.SLDPRT | rebuilt | Boss-Extrude1 negative |
| motorClip_v1.SLDPRT | not fully decoded | Cut-Extrude1: moCut_c not converted yet; Sketch3: no plane reference found; Sketch4: arc 1: no centre found |
| setScrew_M2x2_5_92015A207.SLDPRT | pre-2015 |  |
| shaft_3x22mm.SLDPRT | rebuilt | Boss-Extrude1 negative |
| shaft_3x55mm.SLDPRT | rebuilt | Boss-Extrude1 symmetric |
| spring_base_tab_v1.SLDPRT | not fully decoded | Sketch5: no plane reference found |
| spring_base_v1.SLDPRT | mismatch |  |
| spring_holder_v1.SLDPRT | not fully decoded | Sketch2: line 3 has 1 end points |
| Axle Rod.SLDPRT | rebuilt | Boss-Extrude1 symmetric |
| Boom Cylinder.SLDPRT | not fully decoded | Sketch1: line 0 has 1 end points |
| Boom Rod.SLDPRT | not fully decoded | Sketch2: line 0 has 1 end points |
| Boom.SLDPRT | not fully decoded | Sketch1: line 0 has 1 end points; Sketch1: line 1 has 1 end points; Sketch1: line 2 has 1 end points; Sketch1: line 3 has 1 end points |
| Bucket.SLDPRT | not fully decoded | Shell1: moShell_c not converted yet; Mirror1: moMirrorSolid_c not converted yet; Combine1: moCombineBodies_c not converted yet; LPattern1: moLPattern_c not converted yet |
| Connecting Rod.SLDPRT | not fully decoded | Sketch1: arc 3: no centre found |
| Differential.SLDPRT | not fully decoded | Mirror1: moMirrorSolid_c not converted yet; Cut-Extrude1: fillet's size or edges not read; Dome1: moDome_c not converted yet; Cut-Extrude2: fillet's size or edges not read |
| Front Body.SLDPRT | not fully decoded | Draft1: moDraft_c not converted yet; Dome2: moDome_c not converted yet; Mirror2: moMirrorSolid_c not converted yet; Combine1: moCombineBodies_c not converted yet |
| Rear Body.SLDPRT | not fully decoded | Draft1: moDraft_c not converted yet; LPattern1: moLPattern_c not converted yet; Draft2: moDraft_c not converted yet; 3DSketch1: mo3DProfileFeature_c not converted yet |
| Rim.SLDPRT | not fully decoded | Sketch1: line 0 has 1 end points |
| Rocker Arm Cylinder.SLDPRT | not fully decoded | Sketch1: line 0 has 1 end points |
| Rocker Arm Rod.SLDPRT | not fully decoded | Sweep1: moSweep_c not converted yet; Dome1: moDome_c not converted yet; Sketch1: arc 0: no centre found |
| Rocker Arm.SLDPRT | not fully decoded | Sketch1: line 1 has 1 end points; Sketch1: arc 3: no centre found; Sketch1: arc 1: no centre found; Sketch3: arc 1: no centre found |
| Screw.SLDPRT | mismatch |  |
| Tyre.SLDPRT | not fully decoded | Surface-Offset1: moOffsetRefSurface_c not converted yet; Surface-Extend1: moExtendRefSurface_c not converted yet; Fillet1: fillet's size or edges not read; Boundary1: moNetBlend_c not converted yet |
| BETON BORU KELEP荅S_U SAPLAMA.sldprt | imported body |  |
| FORGED SOCKET HEAD CAP SCREW X METRIC - ANSI B18.3.1M X M12 X 1.75 X 50.sldprt | imported body |  |
| HEX NUT - ANSI B 18.2.4.1 M - M20 X 2.5.sldprt | imported body |  |
| KELEP荅 YAST_2.sldprt | imported body |  |
| K軱軹 MAFSAL PIMI.sldprt | imported body |  |
| LUBRICATING NIPPLE, CONED TYPE A - DIN 71412 - AM8 X 1 CONED SHORT.sldprt | imported body |  |
| MERKEZ PIMI.sldprt | imported body |  |
| PART1(1)(1).sldprt | imported body |  |
| PART1(1).sldprt | imported body |  |
| PART1.sldprt | imported body |  |
| PART10.sldprt | imported body |  |
| PART11.sldprt | imported body |  |
| PART12.sldprt | imported body |  |
| PART13.sldprt | imported body |  |
| PART14.sldprt | imported body |  |
| PART15.sldprt | imported body |  |
| PART16.sldprt | imported body |  |
| PART17.sldprt | imported body |  |
| PART18.sldprt | imported body |  |
| PART19.sldprt | imported body |  |
| PART2.sldprt | imported body |  |
| PART20.sldprt | imported body |  |
| PART21.sldprt | imported body |  |
| PART22.sldprt | imported body |  |
| PART23.sldprt | imported body |  |
| PART25.sldprt | imported body |  |
| PART3.sldprt | imported body |  |
| PART33_2.sldprt | imported body |  |
| PART35.sldprt | imported body |  |
| PART4.sldprt | imported body |  |
| PART41.sldprt | imported body |  |
| PART44.sldprt | imported body |  |
| PART48.sldprt | imported body |  |
| PART49.sldprt | imported body |  |
| PART5.sldprt | imported body |  |
| PART50.sldprt | imported body |  |
| PART54.sldprt | imported body |  |
| PART56.sldprt | imported body |  |
| PART58.sldprt | imported body |  |
| PART59.sldprt | imported body |  |
| PART6.sldprt | imported body |  |
| PART60.sldprt | imported body |  |
| PART7.sldprt | imported body |  |
| PART75.sldprt | imported body |  |
| PART8.sldprt | imported body |  |
| PART83.sldprt | imported body |  |
| PART84.sldprt | imported body |  |
| PART85.sldprt | imported body |  |
| PART9.sldprt | imported body |  |
| PG21-SOMUN.sldprt | imported body |  |
| PIPE - DIN2448 - 60.3 X 4 - S235JR - 329.09593496.sldprt | imported body |  |
| PIPE - DIN2448 - 60.3 X 4 - S235JR - 430.sldprt | imported body |  |
| PIPE - DIN2448 - 60.3 X 4 - S235JR - 470.sldprt | imported body |  |
| PIPE - DIN2448 - 60.3 X 4 - S235JR - 600_2.sldprt | imported body |  |
| RULMAN.sldprt | imported body |  |
| RVH18 B軷軳C_S軱軳D軷 G諺DES_.sldprt | imported body |  |
| RVH18 B軷軳C_S軱軳D軷 ROTU.sldprt | imported body |  |
| RVH18 芮躈C_BOM YEN_BA_PAR茿SI.sldprt | imported body |  |
| RVH18 芮躈C_S軱軱軳D軷 K躌ESEL MAFSAL ROTU.sldprt | imported body |  |
| RVH18 芮躈C_S軱軳D軷 G諺DES_.sldprt | imported body |  |
| RVH18 軰軳C_BOOM YEN_U_PAR茿SI.sldprt | imported body |  |
| RVH18 軰軳C_S軱軳D軷 G諺DES_.sldprt | imported body |  |
| RVH18 軰軳C_S軱軳D軷 ROTU.sldprt | imported body |  |
| SCHWING DN A25 KELEP荅 2.sldprt | imported body |  |
| SCHWING DN A25 KELEP荅.sldprt | imported body |  |
| SCHW齆G DN 125 KAYNAKLI KELEP荅 G諺DES_.sldprt | imported body |  |
| SCHW齆G DN 125 KAYNAKLI KELEP荅 KEPI.sldprt | imported body |  |
| SIKMASOMUNU.sldprt | imported body |  |
| SPRING RETAINING RING - DIN 471 - 190 X 4.sldprt | imported body |  |
| WASHER - DIN 125-1 - B 21.sldprt | imported body |  |
| WASHER - DIN 125-2 -  21.sldprt | imported body |  |
| 8om3wpart1.SLDPRT | not fully decoded | Surface-Loft1: moBlendRefSurface_c not converted yet; Surface-Plane1: moPlanarSurface_c not converted yet; Surface-Trim1: moTrimRefSurface_c not converted yet; Surface-Knit1: moSewRefSurface_c not converted yet |
| 8om3wpart2.SLDPRT | not fully decoded | Sketch2<4>: no plane reference found |
| Push Button Red.SLDPRT | not fully decoded | Sketch1: arc 1: no centre found |
| Push Button green.SLDPRT | not fully decoded | Sketch1: arc 1: no centre found |
| antenn connector.SLDPRT | not fully decoded | Резьба1: moSweepThread_c not converted yet; Резьба2: moSweepThread_c not converted yet |
| button_trigger.SLDPRT | not fully decoded | Sketch1: line 8 has 1 end points |
| dyn_d52h27mm.SLDPRT | not fully decoded | Extrude-Thin1: moBossThin_c not converted yet; CirPattern2: moCirPattern_c not converted yet; Sketch2: line 15 has 1 end points; Sketch3: line 5 has 1 end points |
| dynamic_FD92-7B 4Om_10W.SLDPRT | not fully decoded | Поверхность-Повернуть2: moRevolvRefSurf_c not converted yet; Поверхность-Повернуть3: moRevolvRefSurf_c not converted yet; Придать толщину3: moThicken_c not converted yet; Придать толщину4: moThicken_c not converted yet |
| on_off switcher_.SLDPRT | not fully decoded | Cosmetic Thread1: moCosmeticThread_c not converted yet; Extrude-Thin1: moBossThin_c not converted yet; Surface-Offset1: moOffsetRefSurface_c not converted yet; Thicken1: moThicken_c not converted yet |
| speaker.SLDPRT | not fully decoded | CirPattern1: moCirPattern_c not converted yet; Cut-Extrude-Thin1: moCutThin_c not converted yet; Sketch1: line 0 has 1 end points; Sketch4: line 15 has 1 end points |
| tamper.SLDPRT | not fully decoded | Extrude-Thin1: moBossThin_c not converted yet; Mirror1: moMirrorPattern_c not converted yet; Sketch2: line 5 has 1 end points |
| GRIPER.SLDPRT | not fully decoded | Extrude-Thin1: moBossThin_c not converted yet; Rib1: moRib_c not converted yet; Mirror3: moMirrorPattern_c not converted yet; Sketch1: line 0 has 1 end points |
| Part T5.SLDPRT | not fully decoded | Sketch1: arc 3: no centre found |
| Part T6.SLDPRT | not fully decoded | Sketch1: arc 3: no centre found |
| Part T9.SLDPRT | rebuilt | Boss-Extrude1 positive, Cut-Extrude1 positive |
| Part1_0.SLDPRT | not fully decoded | Sketch1: arc 3: no centre found |
| Part2_T270.SLDPRT | not fully decoded | spur gear_iso-1-solid1: imported body among features; Sketch3: no plane reference found; Sketch2: line 4 has 1 end points |
| PartT8.SLDPRT | rebuilt | Boss-Extrude1 positive |
| PartT_7.SLDPRT | not fully decoded | Sketch1: arc 1: no centre found; Sketch1: arc 6: no centre found |
| part T370.SLDPRT | not fully decoded | Body-Move/Copy1: moMoveCopyBody_c not converted yet; spur gear_iso-1-solid1: imported body among features; Sketch3: line 4 has 1 end points |
| 2MM Pin.SLDPRT | rebuilt | Boss-Extrude1 positive |
| Base.SLDPRT | not fully decoded | Cut-Extrude2: moCut_c not converted yet; Thread1: moSweepThread_c not converted yet; Thread2: moSweepThread_c not converted yet; Thread3: moSweepThread_c not converted yet |
| Bearing Cap.SLDPRT | not fully decoded | Sketch2<3>: no plane reference found |
| Bearing.SLDPRT | not fully decoded | Mirror1: moMirrorPattern_c not converted yet |
| Concentric Strap.SLDPRT | not fully decoded | Split1: moSplit_c not converted yet; Fillet1: fillet's size or edges not read; Sketch4<3>: no plane reference found; Sketch1: arc 3: no centre found |
| Concentric.SLDPRT | not fully decoded | Sketch3: arc 0: no centre found |
| Conrod.SLDPRT | mismatch |  |
| Crank.SLDPRT | not fully decoded | Sketch2<4>: no plane reference found |
| Cross Slide.SLDPRT | not fully decoded | Cut-Extrude1: moFromEndSpec_c not converted yet; Thread1: moSweepThread_c not converted yet; Thread2: moSweepThread_c not converted yet; Thread3: moSweepThread_c not converted yet |
| Cylinder.SLDPRT | not fully decoded | Mirror1: moMirrorPattern_c not converted yet; Thread1: moSweepThread_c not converted yet; Sketch1: arc 1: no centre found |
| Flywheel.SLDPRT | not fully decoded | Mirror1: moMirrorPattern_c not converted yet; Mirror3: moMirrorPattern_c not converted yet; Sketch3<3>: no plane reference found; Sketch3<4>: no plane reference found |
| Front Cylinder Cover.SLDPRT | mismatch |  |
| Key Way.SLDPRT | not fully decoded | Fillet2: fillet's size or edges not read; Sketch3: line 5 has 1 end points; Sketch3: line 9 has 1 end points; Sketch5: line 5 has 1 end points |
| Pin for Crank.SLDPRT | rebuilt | Boss-Extrude1 positive |
| Piston crank.SLDPRT | not fully decoded | Thread1: moSweepThread_c not converted yet; Thread2: moSweepThread_c not converted yet |
| Piston.SLDPRT | not fully decoded | Thread1: moSweepThread_c not converted yet; Sketch2<2>: no plane reference found |
| Rear Cylidner Cover.SLDPRT | not fully decoded | Sketch1: arc 10: no centre found; Sketch2: arc 1: no centre found |
| Slide.SLDPRT | mismatch |  |
| Valve Lid.SLDPRT | not fully decoded | Thread1: moSweepThread_c not converted yet |
| Valve Operating Bar.SLDPRT | rebuilt | Boss-Extrude1 positive |
| Valve Operating Conrod.SLDPRT | not fully decoded | Sketch2<3>: no plane reference found |
| Valve Slide.SLDPRT | mismatch |  |
| Valve slide Bar.SLDPRT | rebuilt | Boss-Extrude1 positive, Cut-Extrude1 negative |
| Valve_1.SLDPRT | not fully decoded | Cut-Extrude4: moCut_c not converted yet; Mirror1: moMirrorPattern_c not converted yet; Sketch3<3>: no plane reference found |
| Cheville bois 10x10.SLDPRT | rebuilt | Boss.-Extru.1 symmetric |
| Desk-29_101.SLDPRT | not fully decoded | Congé1: fillet's size or edges not read; D:\CAO\SOLIDWORKS\Office\Desks\Desk-29\Desk-29_001.SLDASM: moExtFeature_c not converted yet; Diamètre du perçage Ø10.0 (10)1: hole's size not read; Esquisse2: no plane reference found |
| Desk-29_102.SLDPRT | not fully decoded | Enlèv. mat.-Extru.2: moCut_c not converted yet; Esquisse2: line 5 has 1 end points |
| Desk-29_103.SLDPRT | not fully decoded | Fraisage pour vis à tête fraisée M81: hole's size not read; Fraisage pour vis à tête fraisée M82: hole's size not read |
| Desk-29_104.SLDPRT | not fully decoded | Fraisage pour vis à tête fraisée M81: hole's size not read; Fraisage pour vis à tête fraisée M82: hole's size not read |
| Karman_101a.SLDPRT | not fully decoded | Courbe1: moRefCurve_c not converted yet; Surface-Lissage-assise: moBlendRefSurface_c not converted yet; Surface frontière1: moNetBlend_c not converted yet; Intersect assise: moSculpt_c not converted yet |
| Karman_201a.SLDPRT | mismatch |  |
| Karman_202a.SLDPRT | not fully decoded | Répétition circulaire1: moCirPattern_c not converted yet; Esquisse3: line 8 has 1 end points; Esquisse3: line 9 has 1 end points |
| Vis FX M6x80.SLDPRT | pre-2015 |  |
| WOOD INSERT M8x20.SLDPRT | not fully decoded | Axe1: moRefAxis_c not converted yet; WOOD INSERT M8x20: imported body among features |
| 11R22.5 10 STUD 285 PCD.SLDPRT | not fully decoded | CV22582504 (SW2012).STEP-1-solid1: imported body among features; CV22582504 (SW2012).STEP-1-solid2: imported body among features; 11R22.5-275, TYRE.STEP-1-solid1: imported body among features; Sketch1: arc 1: no centre found |
| 11R22.5 10 STUD 335 PCD.SLDPRT | not fully decoded | Body-Move/Copy1: moMoveCopyBody_c not converted yet; Body-Move/Copy2: moMoveCopyBody_c not converted yet; CV22582504 (SW2012).STEP-1-solid1: imported body among features; CV22582504 (SW2012).STEP-1-solid2: imported body among features |
| ADBLUE TANKk.SLDPRT | not fully decoded | Combine1: moCombineBodies_c not converted yet; Split1: moSplit_c not converted yet; Combine2: moCombineBodies_c not converted yet; Body-Move/Copy1: moMoveCopyBody_c not converted yet |
| Battery box.SLDPRT | not fully decoded | Sheet-Metal: moTemplateSheetMetal_c not converted yet; Convert-Solid1: moSolidToSheetMetal_c not converted yet; Edge-Flange1: moEdgeFlange_c not converted yet; EdgeBend1: moOneBend_c not converted yet |
| DPF Silencer.SLDPRT | not fully decoded | Weldment: moWeldmentFeature_c not converted yet; As3679.1-300plus ea 50X50X3(1): moWeldMemberFeat_c not converted yet; Body-Move/Copy2: moMoveCopyBody_c not converted yet; Body-Move/Copy3: moMoveCopyBody_c not converted yet |
| FUEL TANK.SLDPRT | not fully decoded | FUEL TANK.stp<1>: moMBimport_c not converted yet; CirPattern1: moCirPattern_c not converted yet; Split1: moSplit_c not converted yet; Split2: moSplit_c not converted yet |
| MODIFIED-KHitch Drum brake, air suspension and axle.SLDPRT | not fully decoded | KHitch Drum brake, air suspension and axle.STEP<1>: moMBimport_c not converted yet; Body-Move/Copy1: moMoveCopyBody_c not converted yet; Body-Move/Copy2: moMoveCopyBody_c not converted yet; Sketch1: no plane reference found |
| NARVA Model 42 Tail Light.SLDPRT | not fully decoded | Split2: moSplit_c not converted yet; Fillet2: fillet's size or edges not read; Sketch6: arc 5: no centre found |
| Sitrack G7 ChassisA.SLDPRT | not fully decoded | Weldment: moWeldmentFeature_c not converted yet; Sweep1: moSweep_c not converted yet; Mirror4: moMirrorSolid_c not converted yet; Sheet-Metal: moTemplateSheetMetal_c not converted yet |
| Sitrak C7.SLDPRT | not fully decoded | Sweep1: moSweep_c not converted yet; Loft1: moBlend_c not converted yet; Sweep2: moSweep_c not converted yet; Loft2: moBlend_c not converted yet |
| Axle Rod.SLDPRT | rebuilt | Boss-Extrude1 symmetric |
| Boom Cylinder.SLDPRT | not fully decoded | Sketch1: line 0 has 1 end points |
| Boom Rod.SLDPRT | not fully decoded | Sketch2: line 0 has 1 end points |
| Boom.SLDPRT | not fully decoded | Sketch1: line 0 has 1 end points; Sketch1: line 1 has 1 end points; Sketch1: line 2 has 1 end points; Sketch1: line 3 has 1 end points |
| Bucket.SLDPRT | not fully decoded | Shell1: moShell_c not converted yet; Mirror1: moMirrorSolid_c not converted yet; Combine1: moCombineBodies_c not converted yet; LPattern1: moLPattern_c not converted yet |
| Connecting Rod.SLDPRT | not fully decoded | Sketch1: arc 3: no centre found |
| Differential.SLDPRT | not fully decoded | Mirror1: moMirrorSolid_c not converted yet; Cut-Extrude1: fillet's size or edges not read; Dome1: moDome_c not converted yet; Cut-Extrude2: fillet's size or edges not read |
| Front Body.SLDPRT | not fully decoded | Draft1: moDraft_c not converted yet; Dome2: moDome_c not converted yet; Mirror2: moMirrorSolid_c not converted yet; Combine1: moCombineBodies_c not converted yet |
| Rear Body.SLDPRT | not fully decoded | Draft1: moDraft_c not converted yet; LPattern1: moLPattern_c not converted yet; Draft2: moDraft_c not converted yet; 3DSketch1: mo3DProfileFeature_c not converted yet |
| Rim.SLDPRT | not fully decoded | Sketch1: line 0 has 1 end points |
| Rocker Arm Cylinder.SLDPRT | not fully decoded | Sketch1: line 0 has 1 end points |
| Rocker Arm Rod.SLDPRT | not fully decoded | Sweep1: moSweep_c not converted yet; Dome1: moDome_c not converted yet; Sketch1: arc 0: no centre found |
| Rocker Arm.SLDPRT | not fully decoded | Sketch1: line 1 has 1 end points; Sketch1: arc 3: no centre found; Sketch1: arc 1: no centre found; Sketch3: arc 1: no centre found |
| Screw.SLDPRT | mismatch |  |
| Tyre.SLDPRT | not fully decoded | Surface-Offset1: moOffsetRefSurface_c not converted yet; Surface-Extend1: moExtendRefSurface_c not converted yet; Fillet1: fillet's size or edges not read; Boundary1: moNetBlend_c not converted yet |
| BETON BORU KELEP荅S_U SAPLAMA.sldprt | imported body |  |
| FORGED SOCKET HEAD CAP SCREW X METRIC - ANSI B18.3.1M X M12 X 1.75 X 50.sldprt | imported body |  |
| HEX NUT - ANSI B 18.2.4.1 M - M20 X 2.5.sldprt | imported body |  |
| KELEP荅 YAST_2.sldprt | imported body |  |
| K軱軹 MAFSAL PIMI.sldprt | imported body |  |
| LUBRICATING NIPPLE, CONED TYPE A - DIN 71412 - AM8 X 1 CONED SHORT.sldprt | imported body |  |
| MERKEZ PIMI.sldprt | imported body |  |
| PART1(1)(1).sldprt | imported body |  |
| PART1(1).sldprt | imported body |  |
| PART1.sldprt | imported body |  |
| PART10.sldprt | imported body |  |
| PART11.sldprt | imported body |  |
| PART12.sldprt | imported body |  |
| PART13.sldprt | imported body |  |
| PART14.sldprt | imported body |  |
| PART15.sldprt | imported body |  |
| PART16.sldprt | imported body |  |
| PART17.sldprt | imported body |  |
| PART18.sldprt | imported body |  |
| PART19.sldprt | imported body |  |
| PART2.sldprt | imported body |  |
| PART20.sldprt | imported body |  |
| PART21.sldprt | imported body |  |
| PART22.sldprt | imported body |  |
| PART23.sldprt | imported body |  |
| PART25.sldprt | imported body |  |
| PART3.sldprt | imported body |  |
| PART33_2.sldprt | imported body |  |
| PART35.sldprt | imported body |  |
| PART4.sldprt | imported body |  |
| PART41.sldprt | imported body |  |
| PART44.sldprt | imported body |  |
| PART48.sldprt | imported body |  |
| PART49.sldprt | imported body |  |
| PART5.sldprt | imported body |  |
| PART50.sldprt | imported body |  |
| PART54.sldprt | imported body |  |
| PART56.sldprt | imported body |  |
| PART58.sldprt | imported body |  |
| PART59.sldprt | imported body |  |
| PART6.sldprt | imported body |  |
| PART60.sldprt | imported body |  |
| PART7.sldprt | imported body |  |
| PART75.sldprt | imported body |  |
| PART8.sldprt | imported body |  |
| PART83.sldprt | imported body |  |
| PART84.sldprt | imported body |  |
| PART85.sldprt | imported body |  |
| PART9.sldprt | imported body |  |
| PG21-SOMUN.sldprt | imported body |  |
| PIPE - DIN2448 - 60.3 X 4 - S235JR - 329.09593496.sldprt | imported body |  |
| PIPE - DIN2448 - 60.3 X 4 - S235JR - 430.sldprt | imported body |  |
| PIPE - DIN2448 - 60.3 X 4 - S235JR - 470.sldprt | imported body |  |
| PIPE - DIN2448 - 60.3 X 4 - S235JR - 600_2.sldprt | imported body |  |
| RULMAN.sldprt | imported body |  |
| RVH18 B軷軳C_S軱軳D軷 G諺DES_.sldprt | imported body |  |
| RVH18 B軷軳C_S軱軳D軷 ROTU.sldprt | imported body |  |
| RVH18 芮躈C_BOM YEN_BA_PAR茿SI.sldprt | imported body |  |
| RVH18 芮躈C_S軱軱軳D軷 K躌ESEL MAFSAL ROTU.sldprt | imported body |  |
| RVH18 芮躈C_S軱軳D軷 G諺DES_.sldprt | imported body |  |
| RVH18 軰軳C_BOOM YEN_U_PAR茿SI.sldprt | imported body |  |
| RVH18 軰軳C_S軱軳D軷 G諺DES_.sldprt | imported body |  |
| RVH18 軰軳C_S軱軳D軷 ROTU.sldprt | imported body |  |
| SCHWING DN A25 KELEP荅 2.sldprt | imported body |  |
| SCHWING DN A25 KELEP荅.sldprt | imported body |  |
| SCHW齆G DN 125 KAYNAKLI KELEP荅 G諺DES_.sldprt | imported body |  |
| SCHW齆G DN 125 KAYNAKLI KELEP荅 KEPI.sldprt | imported body |  |
| SIKMASOMUNU.sldprt | imported body |  |
| SPRING RETAINING RING - DIN 471 - 190 X 4.sldprt | imported body |  |
| WASHER - DIN 125-1 - B 21.sldprt | imported body |  |
| WASHER - DIN 125-2 -  21.sldprt | imported body |  |
| 8om3wpart1.SLDPRT | not fully decoded | Surface-Loft1: moBlendRefSurface_c not converted yet; Surface-Plane1: moPlanarSurface_c not converted yet; Surface-Trim1: moTrimRefSurface_c not converted yet; Surface-Knit1: moSewRefSurface_c not converted yet |
| 8om3wpart2.SLDPRT | not fully decoded | Sketch2<4>: no plane reference found |
| Push Button Red.SLDPRT | not fully decoded | Sketch1: arc 1: no centre found |
| Push Button green.SLDPRT | not fully decoded | Sketch1: arc 1: no centre found |
| antenn connector.SLDPRT | not fully decoded | Резьба1: moSweepThread_c not converted yet; Резьба2: moSweepThread_c not converted yet |
| button_trigger.SLDPRT | not fully decoded | Sketch1: line 8 has 1 end points |
| dyn_d52h27mm.SLDPRT | not fully decoded | Extrude-Thin1: moBossThin_c not converted yet; CirPattern2: moCirPattern_c not converted yet; Sketch2: line 15 has 1 end points; Sketch3: line 5 has 1 end points |
| dynamic_FD92-7B 4Om_10W.SLDPRT | not fully decoded | Поверхность-Повернуть2: moRevolvRefSurf_c not converted yet; Поверхность-Повернуть3: moRevolvRefSurf_c not converted yet; Придать толщину3: moThicken_c not converted yet; Придать толщину4: moThicken_c not converted yet |
| on_off switcher_.SLDPRT | not fully decoded | Cosmetic Thread1: moCosmeticThread_c not converted yet; Extrude-Thin1: moBossThin_c not converted yet; Surface-Offset1: moOffsetRefSurface_c not converted yet; Thicken1: moThicken_c not converted yet |
| speaker.SLDPRT | not fully decoded | CirPattern1: moCirPattern_c not converted yet; Cut-Extrude-Thin1: moCutThin_c not converted yet; Sketch1: line 0 has 1 end points; Sketch4: line 15 has 1 end points |
| tamper.SLDPRT | not fully decoded | Extrude-Thin1: moBossThin_c not converted yet; Mirror1: moMirrorPattern_c not converted yet; Sketch2: line 5 has 1 end points |
| GRIPER.SLDPRT | not fully decoded | Extrude-Thin1: moBossThin_c not converted yet; Rib1: moRib_c not converted yet; Mirror3: moMirrorPattern_c not converted yet; Sketch1: line 0 has 1 end points |
| Part T5.SLDPRT | not fully decoded | Sketch1: arc 3: no centre found |
| Part T6.SLDPRT | not fully decoded | Sketch1: arc 3: no centre found |
| Part T9.SLDPRT | rebuilt | Boss-Extrude1 positive, Cut-Extrude1 positive |
| Part1_0.SLDPRT | not fully decoded | Sketch1: arc 3: no centre found |
| Part2_T270.SLDPRT | not fully decoded | spur gear_iso-1-solid1: imported body among features; Sketch3: no plane reference found; Sketch2: line 4 has 1 end points |
| PartT8.SLDPRT | rebuilt | Boss-Extrude1 positive |
| PartT_7.SLDPRT | not fully decoded | Sketch1: arc 1: no centre found; Sketch1: arc 6: no centre found |
| part T370.SLDPRT | not fully decoded | Body-Move/Copy1: moMoveCopyBody_c not converted yet; spur gear_iso-1-solid1: imported body among features; Sketch3: line 4 has 1 end points |
| 2MM Pin.SLDPRT | rebuilt | Boss-Extrude1 positive |
| Base.SLDPRT | not fully decoded | Cut-Extrude2: moCut_c not converted yet; Thread1: moSweepThread_c not converted yet; Thread2: moSweepThread_c not converted yet; Thread3: moSweepThread_c not converted yet |
| Bearing Cap.SLDPRT | not fully decoded | Sketch2<3>: no plane reference found |
| Bearing.SLDPRT | not fully decoded | Mirror1: moMirrorPattern_c not converted yet |
| Concentric Strap.SLDPRT | not fully decoded | Split1: moSplit_c not converted yet; Fillet1: fillet's size or edges not read; Sketch4<3>: no plane reference found; Sketch1: arc 3: no centre found |
| Concentric.SLDPRT | not fully decoded | Sketch3: arc 0: no centre found |
| Conrod.SLDPRT | mismatch |  |
| Crank.SLDPRT | not fully decoded | Sketch2<4>: no plane reference found |
| Cross Slide.SLDPRT | not fully decoded | Cut-Extrude1: moFromEndSpec_c not converted yet; Thread1: moSweepThread_c not converted yet; Thread2: moSweepThread_c not converted yet; Thread3: moSweepThread_c not converted yet |
| Cylinder.SLDPRT | not fully decoded | Mirror1: moMirrorPattern_c not converted yet; Thread1: moSweepThread_c not converted yet; Sketch1: arc 1: no centre found |
| Flywheel.SLDPRT | not fully decoded | Mirror1: moMirrorPattern_c not converted yet; Mirror3: moMirrorPattern_c not converted yet; Sketch3<3>: no plane reference found; Sketch3<4>: no plane reference found |
| Front Cylinder Cover.SLDPRT | mismatch |  |
| Key Way.SLDPRT | not fully decoded | Fillet2: fillet's size or edges not read; Sketch3: line 5 has 1 end points; Sketch3: line 9 has 1 end points; Sketch5: line 5 has 1 end points |
| Pin for Crank.SLDPRT | rebuilt | Boss-Extrude1 positive |
| Piston crank.SLDPRT | not fully decoded | Thread1: moSweepThread_c not converted yet; Thread2: moSweepThread_c not converted yet |
| Piston.SLDPRT | not fully decoded | Thread1: moSweepThread_c not converted yet; Sketch2<2>: no plane reference found |
| Rear Cylidner Cover.SLDPRT | not fully decoded | Sketch1: arc 10: no centre found; Sketch2: arc 1: no centre found |
| Slide.SLDPRT | mismatch |  |
| Valve Lid.SLDPRT | not fully decoded | Thread1: moSweepThread_c not converted yet |
| Valve Operating Bar.SLDPRT | rebuilt | Boss-Extrude1 positive |
| Valve Operating Conrod.SLDPRT | not fully decoded | Sketch2<3>: no plane reference found |
| Valve Slide.SLDPRT | mismatch |  |
| Valve slide Bar.SLDPRT | rebuilt | Boss-Extrude1 positive, Cut-Extrude1 negative |
| Valve_1.SLDPRT | not fully decoded | Cut-Extrude4: moCut_c not converted yet; Mirror1: moMirrorPattern_c not converted yet; Sketch3<3>: no plane reference found |
| Cheville bois 10x10.SLDPRT | rebuilt | Boss.-Extru.1 symmetric |
| Desk-29_101.SLDPRT | not fully decoded | Congé1: fillet's size or edges not read; D:\CAO\SOLIDWORKS\Office\Desks\Desk-29\Desk-29_001.SLDASM: moExtFeature_c not converted yet; Diamètre du perçage Ø10.0 (10)1: hole's size not read; Esquisse2: no plane reference found |
| Desk-29_102.SLDPRT | not fully decoded | Enlèv. mat.-Extru.2: moCut_c not converted yet; Esquisse2: line 5 has 1 end points |
| Desk-29_103.SLDPRT | not fully decoded | Fraisage pour vis à tête fraisée M81: hole's size not read; Fraisage pour vis à tête fraisée M82: hole's size not read |
| Desk-29_104.SLDPRT | not fully decoded | Fraisage pour vis à tête fraisée M81: hole's size not read; Fraisage pour vis à tête fraisée M82: hole's size not read |
| Karman_101a.SLDPRT | not fully decoded | Courbe1: moRefCurve_c not converted yet; Surface-Lissage-assise: moBlendRefSurface_c not converted yet; Surface frontière1: moNetBlend_c not converted yet; Intersect assise: moSculpt_c not converted yet |
| Karman_201a.SLDPRT | mismatch |  |
| Karman_202a.SLDPRT | not fully decoded | Répétition circulaire1: moCirPattern_c not converted yet; Esquisse3: line 8 has 1 end points; Esquisse3: line 9 has 1 end points |
| Vis FX M6x80.SLDPRT | pre-2015 |  |
| WOOD INSERT M8x20.SLDPRT | not fully decoded | Axe1: moRefAxis_c not converted yet; WOOD INSERT M8x20: imported body among features |
| 11R22.5 10 STUD 285 PCD.SLDPRT | not fully decoded | CV22582504 (SW2012).STEP-1-solid1: imported body among features; CV22582504 (SW2012).STEP-1-solid2: imported body among features; 11R22.5-275, TYRE.STEP-1-solid1: imported body among features; Sketch1: arc 1: no centre found |
| 11R22.5 10 STUD 335 PCD.SLDPRT | not fully decoded | Body-Move/Copy1: moMoveCopyBody_c not converted yet; Body-Move/Copy2: moMoveCopyBody_c not converted yet; CV22582504 (SW2012).STEP-1-solid1: imported body among features; CV22582504 (SW2012).STEP-1-solid2: imported body among features |
| ADBLUE TANKk.SLDPRT | not fully decoded | Combine1: moCombineBodies_c not converted yet; Split1: moSplit_c not converted yet; Combine2: moCombineBodies_c not converted yet; Body-Move/Copy1: moMoveCopyBody_c not converted yet |
| Battery box.SLDPRT | not fully decoded | Sheet-Metal: moTemplateSheetMetal_c not converted yet; Convert-Solid1: moSolidToSheetMetal_c not converted yet; Edge-Flange1: moEdgeFlange_c not converted yet; EdgeBend1: moOneBend_c not converted yet |
| DPF Silencer.SLDPRT | not fully decoded | Weldment: moWeldmentFeature_c not converted yet; As3679.1-300plus ea 50X50X3(1): moWeldMemberFeat_c not converted yet; Body-Move/Copy2: moMoveCopyBody_c not converted yet; Body-Move/Copy3: moMoveCopyBody_c not converted yet |
| FUEL TANK.SLDPRT | not fully decoded | FUEL TANK.stp<1>: moMBimport_c not converted yet; CirPattern1: moCirPattern_c not converted yet; Split1: moSplit_c not converted yet; Split2: moSplit_c not converted yet |
| MODIFIED-KHitch Drum brake, air suspension and axle.SLDPRT | not fully decoded | KHitch Drum brake, air suspension and axle.STEP<1>: moMBimport_c not converted yet; Body-Move/Copy1: moMoveCopyBody_c not converted yet; Body-Move/Copy2: moMoveCopyBody_c not converted yet; Sketch1: no plane reference found |
| NARVA Model 42 Tail Light.SLDPRT | not fully decoded | Split2: moSplit_c not converted yet; Fillet2: fillet's size or edges not read; Sketch6: arc 5: no centre found |
| Sitrack G7 ChassisA.SLDPRT | not fully decoded | Weldment: moWeldmentFeature_c not converted yet; Sweep1: moSweep_c not converted yet; Mirror4: moMirrorSolid_c not converted yet; Sheet-Metal: moTemplateSheetMetal_c not converted yet |
| Sitrak C7.SLDPRT | not fully decoded | Sweep1: moSweep_c not converted yet; Loft1: moBlend_c not converted yet; Sweep2: moSweep_c not converted yet; Loft2: moBlend_c not converted yet |
