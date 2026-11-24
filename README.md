# sw2sc — SolidWorks to SolidCraft converter

Converts SolidWorks part (`.sldprt`) and assembly (`.sldasm`) files into
[SolidCraft](https://github.com/tangency-labs/solidcraft) designs (`.solidcraft`),
keeping the model **structure**.

* **Clean-room.** Reads the files directly. It does not use the SolidWorks API or
  SDK, needs no SolidWorks licence, and contains no proprietary code. File layouts
  come from public specifications (Microsoft MS-CFB and MS-OLEPS, the Office
  custom-properties schema) and from studying sample files. See `docs/clean-room.md`.
* **No dependencies.** Python 3.9+ standard library only.

## Usage

Double-click `Vault.cmd` to open the vault window (see `docs/vault.md`), or use the command line:

```bash
python -m sw2sc convert "My Assembly.SLDASM"            # writes My Assembly.solidcraft next to it
python -m sw2sc convert part.sldprt -o out/part.solidcraft
python -m sw2sc inspect "My Assembly.SLDASM"            # print what is read: tree, features, properties
python -m sw2sc survey folder1 folder2                   # convert everything, write logs/survey-<version>.md
python -m sw2sc vault import "D:\CAD" "D:\Vault"         # folder tree -> Git vault of linked designs (docs/vault.md)
python -m unittest discover -s tests                     # tests
python tools/check_steps.py <solidcraft-cli> out/step    # open converted STEP files in SolidCraft
python tools/feature_check.py <folder>                   # rebuild each part's feature tree, compare with its solid
python tools/rebuild_triage.py <folder> --names A,B      # where a part's rebuild stops
```

Keep referenced part files next to the assembly (any subfolder works). Without them the
structure still converts, but those parts' properties and feature trees are missing.

## What is migrated (v0.17.1)

| SolidWorks | SolidCraft |
|---|---|
| Assembly tree, nested subassemblies at any depth | components + occurrences (a definition used many times is one component) |
| Instance placement (4×4, metres) | occurrence `transform` (mm), grounded |
| Instance numbers (`bearing<3>`) | occurrence name `bearing:3` |
| Hidden / suppressed instances | `visibility.hidden_occurrences` (suppressed ones are logged too) |
| Custom properties | component `metadata` (description, part number, revision, author…) and `properties` |
| Feature tree: sketches (points, lines, arcs, circles, construction lines, dimensions, relations, offsets), extrudes and cuts (thin, up to a face, through all), revolves, fillets, chamfers, Hole Wizard holes, mirrors, patterns, threads, domes, shells | SolidCraft features of the same kind, each sketch dimension and depth a model parameter (`Sketch2_D1`, `Boss_Extrude1_D1`). A part is written this way only when rebuilding its tree in SolidCraft matches SolidWorks' own solid (volume, area and box within 0.1 %); otherwise it keeps the imported solid and the tree is listed with what is missing |
| Feature tree (names, types, sketch use, dimension values), material, configurations, source file | component metadata under `io.sw2sc.solidworks`, including a TBD entry for every feature not converted |

Part geometry comes from the Parasolid solids stored inside each part, written as STEP text
into an Import feature in the part's component. It is exact for analytic and B-spline faces.
Fillets and a few other surface types are close fits, and some of those parts open in
SolidCraft as surfaces instead of closed solids. Each conversion reports how many faces were
fitted or left out; `--no-geometry` converts structure only.

**Not yet:** mates → joints; draft; full-round fillets; some sketches whose arcs are read as
circles (their second end has no point record); standing models up (SolidWorks is Y-up).
See `ISSUES.md`.

## SolidCraft plugin: open `.sldprt` files directly

`plugin/` is the same converter in Rust, built as a SolidCraft importer plugin: File › Open
in SolidCraft offers SolidWorks parts and opens each one as a new design with its feature tree,
after checking that the rebuilt tree matches the part's own solid (through SolidCraft's
`evaluate` interface). Where it doesn't yet, the part comes in as its solid and the import
report lists what isn't converted.

**Download:** the latest `sw2sc-<version>.zip` is on the
[Releases](https://github.com/bobthecooldad/sw2sc/releases/latest) page. Every push is built and
tested; a new number in `VERSION` on `main` publishes a release (see `.github/workflows/build.yml`).

To build it yourself (Rust with the `wasm32-unknown-unknown` target, and `wasm-tools`):

```powershell
rustup target add wasm32-unknown-unknown
cargo install wasm-tools
powershell -File plugin/build.ps1      # writes plugin/sw2sc.zip
```

Install in SolidCraft: Preferences › Plugins › Install plugin…, choose `plugin/sw2sc.zip`, and
allow the memory it asks for. Assemblies aren't converted by the plugin yet.

## Project files

* `VERSION` — current version (semantic versioning)
* `CHANGELOG.md` — what changed in each version
* `ISSUES.md` — bug and feature log, with IDs
* `logs/` — survey results for each version, run against the sample models

Sample models (`samples/`, `Solidworks Example Grabcad/`) belong to their authors and
are not committed.

## Thanks

- [cadkit-kernel](https://github.com/civilkit/cadkit-kernel) (MIT OR Apache-2.0), another clean-room SolidWorks reader, whose author pointed us to it and whose work guides parts of this one; findings it led to are credited in `docs/clean-room.md`.

## Licence and trademarks

MIT (see `LICENSE`).

SolidWorks is a trademark of Dassault Systèmes; Parasolid is a trademark of Siemens. They are
named here only to say which files this tool reads. This project is not affiliated with,
endorsed by or sponsored by either company, and contains none of their code: it reads the
files directly, from public specifications and from studying sample files (`docs/clean-room.md`).
