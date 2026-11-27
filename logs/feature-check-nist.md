# Feature check

- kernel: solidcraft-cli 0.50.0 at C:\dev\solidcraft\target\release\solidcraft-cli.exe (checkout C:\dev\solidcraft, commit d1fdc0b9c of 2026-11-26 20:05)
- rebuilt, does not match: 12
- not fully decoded: 7

| Part | Result | Notes |
|---|---|---|
| nist_ctc_01_asme1_SW1201_rd.SLDPRT | mismatch | no build to compare |
| nist_ctc_02_asme1_SW1201_rc.SLDPRT | not fully decoded | 3DSketch1: mo3DProfileFeature_c not converted yet |
| nist_ctc_03_asme1_SW1201_rc.SLDPRT | mismatch | no build to compare |
| nist_ctc_04_asme1_SW1201_rd.SLDPRT | mismatch | no build to compare |
| nist_ctc_05_asme1_SW1201_rd.SLDPRT | mismatch | no build to compare |
| nist_ctc_01_asme1_rd_sw1802.SLDPRT | mismatch | too much material (+0.6%): a loop is an island, or a cut didn't take |
| nist_ctc_02_asme1_rc_sw1802.SLDPRT | not fully decoded | 3DSketch1: mo3DProfileFeature_c not converted yet |
| nist_ctc_03_asme1_rc_sw1802.SLDPRT | mismatch | no build to compare |
| nist_ctc_04_asme1_rd_sw1802.SLDPRT | mismatch | no build to compare |
| nist_ctc_05_asme1_rd_sw1802.SLDPRT | mismatch | no build to compare |
| nist_ftc_06_asme1_rd_sw1802.SLDPRT | mismatch | no build to compare |
| nist_ftc_07_asme1_rd_sw1802.SLDPRT | not fully decoded | VarFillet1: VarFillet_c not converted yet; VarFillet3: VarFillet_c not converted yet; Sketch38: sketch text: SolidWorks keeps the words, size and place but not the letters' shapes, so SolidCraft's own lettering can't be matched to the solid exactly |
| nist_ftc_08_asme1_rc_sw1802.SLDPRT | mismatch | no build to compare |
| nist_ftc_09_asme1_rd_sw1802.SLDPRT | not fully decoded | Sketch30: sketch text: SolidWorks keeps the words, size and place but not the letters' shapes, so SolidCraft's own lettering can't be matched to the solid exactly |
| nist_ftc_10_asme1_rb_sw1802.SLDPRT | not fully decoded | 3DSketch1: mo3DProfileFeature_c not converted yet |
| nist_ftc_11_asme1_rb_sw1802.SLDPRT | not fully decoded | Sketch3: sketch text: SolidWorks keeps the words, size and place but not the letters' shapes, so SolidCraft's own lettering can't be matched to the solid exactly |
| nist_ftc_06_asme1_sw1500_rd.SLDPRT | mismatch | no build to compare |
| nist_ftc_08_asme1_sw1500_rc.SLDPRT | mismatch | no build to compare |
| nist_ftc_09_asme1_sw1500_rd.SLDPRT | not fully decoded | Sketch30: sketch text: SolidWorks keeps the words, size and place but not the letters' shapes, so SolidCraft's own lettering can't be matched to the solid exactly |
