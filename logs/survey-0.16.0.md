# Survey 0.16.0 (2026-11-19)

Feature check over Documents, samples, the GrabCAD examples and out/vault-grabcad (which
repeats some samples): 22 rebuilt and match, 14 distinct parts (the 13 of 0.15.1 and PartT8,
with two fillets); 11 rebuilt without a match (idler arms: SolidCraft refuses the R1 outline
fillet; the USB part's Text cut differs; revolve parts); 158 not fully decoded; 142 imported
bodies; 4 older streams not numbered; 12 unreadable. Fillets in the samples: 59 by their
records, 88 more found by name from KeyWords. Unit tests: 56 run, OK (25 skipped where samples
are not reachable from the worktree).
