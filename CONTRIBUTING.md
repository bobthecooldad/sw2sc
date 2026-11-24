# Contributing

Thank you for helping. [ROADMAP.md](ROADMAP.md) lists where help is most useful; `ISSUES.md`
has the detail of each item. Five rules keep the project usable by everyone.

## 1. Clean room

The converter reads SolidWorks files from public specifications and from studying sample files,
and nothing else. Never use the SolidWorks API, SDK, Document Manager or eDrawings, never run
SolidWorks to produce reference data, and never copy code from GPL/LGPL/AGPL converters or from
any leaked or proprietary source. Every finding about the file format goes in
[docs/clean-room.md](docs/clean-room.md) with the evidence for it. If you have worked on the
SolidWorks code base or signed an agreement that covers its formats, please don't contribute
format findings.

## 2. Your files stay yours

Test on your own SolidWorks files as much as you like, but never put them, their names, their
geometry or your folders in a commit, an issue or a log:

- Describe a part by what it has ("a 40-feature part with two through-all cuts and a shell, inch
  units, SolidWorks 2018"), not by its name or path.
- Paste the converter's report with names replaced (`Part A`, `Sketch3` stays as it is).
- Before a pull request, run `python tools/publish.py check`. It finds paths into home and
  cloud folders and e-mail addresses. If you keep a private folder (`~/.sw2sc-private`, described
  at the top of `tools/publish.py`) with your own part names and words, it finds those too.
- Sample files in `samples/` and `Solidworks Example Grabcad/` are third-party downloads and are
  git-ignored: they are not ours to redistribute. Name the public source instead.

## 3. Python and Rust stay the same

`sw2sc/` (Python, the reference) and `plugin/sw2sc-core/` (Rust, the SolidCraft plugin) read the
same files the same way. A change to reading, design writing or the rebuild search goes into
both, and these must show no differences on every part you have:

```powershell
cargo build --release -p sw2sc-core --examples          # in plugin/
$env:PROFILE = "release"
python plugin/tools/compare_features.py <folders...>
python plugin/tools/compare_designs.py <folders...>
```

## 4. Check before you claim

- `python -m unittest discover -s tests` passes (tests needing the third-party samples skip
  without them).
- `cargo test --release -p sw2sc-core` passes.
- Parts that rebuilt before still rebuild. Say which set you checked and what changed, with
  numbers ("21 of 22 rebuild, as before; 4 more of 200 now rebuild").

## 5. Keep the logs

Each change adds an entry to `logs/working-log.md` (what was wrong, how it was found, what changed,
the results) and a line to the `[Unreleased]` section of `CHANGELOG.md`. Open items go in
`ISSUES.md` with an ID. The logs are how the next person avoids redoing your work: write what you
tried that didn't work too.
