# Vault import

`sw2sc vault` turns a folder tree of SolidWorks files into a vault: a folder of SolidCraft
designs with its history in Git.

It follows the direction SolidCraft's contributors chose for versions and PDM (issue 2869
in the SolidCraft repository): designs as text, history in Git, branch and merge. There is
no server and no file locking.

## Use

**Window.** Double-click `Vault.cmd`, or run `python -m sw2sc gui`. The vault window opens in
your browser. Choose the folder with your CAD files and a vault folder, then select **Import**.
Below, the vault's contents can be searched, and selecting an item shows what it contains and
where it is used. The window works on this PC only. Keep the black window that started it open
while you use it.

**Command line.**

```bash
python -m sw2sc vault import "D:\CAD\Projects" "D:\Vault"
```

```bash
python -m sw2sc vault where-used "D:\Vault" bearing_3x6x2
```

```bash
python -m sw2sc vault bom "D:\Vault" Assem4
```

The `where-used` and `bom` commands take a path in the vault, a file name or a part number.
Both walk every level of nested assemblies.

Run `vault import` again after the source changes. It converts only what changed: a changed
part, the subassemblies that use it, and every assembly above them. It then records one Git
commit, so the vault's Git log is the history of the imported data. A run with nothing changed
records no commit.

Options:

- `--no-originals`: don't copy the SolidWorks files into the vault.
- `--no-git`: write the vault without recording a commit.

## Folders

The folder tree beside the designs sorts the vault: **New folder** (inside the folder shown),
**Rename** and **Remove**. Put a design in a folder with the **Folder** picker in its details,
or drag it onto a folder. Removing a folder moves its designs up one level; no design is
deleted. Folders only sort what the window shows: the files stay where the import put them,
so assembly links, releases and the next import keep working. They are kept in
`folders.json` in the vault, and each change is recorded in its history. A design starts in
the folder its SolidWorks file came from.

## What an import checks first

Import a project folder, not a personal one. Before it starts, the import asks when the
folder is your Documents, Desktop or user folder or a whole drive, when only a few of its
files are SolidWorks files, when it is very large, or when the vault holds a different
project (an import keeps the vault in step with its folder, so designs not in the new folder
are removed). Untick **Copy the folder's other files too** to bring only the SolidWorks files.
On the command line the import stops with the reasons; `--yes` goes on anyway and
`--designs-only` leaves the other files out.

## Open in SolidCraft

Select a design and choose **Open in SolidCraft**. Under **Releases**, **Open** pulls that
release out of the vault's history into a temporary folder and opens the copy, so you see it
exactly as released; changing the copy doesn't change the vault.

The window uses the newest SolidCraft app it finds: on the PATH, in its install folder, or a
build in `C:\dev\solidcraft`. To choose one yourself, add `"solidcraft": "<path to
solidcraft.exe>"` to `.sw2sc-gui.json` in your user folder.

If SolidCraft is already open, Open sends the design to that window instead of starting
another (through SolidCraft's local control channel, which is on unless Preferences >
Assistant turns it off). It opens in a tab of its own; only a blank design is replaced, so
unsaved work is never lost. With no window answering, a new one starts. Add
`"reuse_window": false` to `.sw2sc-gui.json` to always start a new window.

## Release states

Every part and assembly in the vault has a state and a revision.

| State | Means | Next |
|---|---|---|
| In Work | being changed | **Submit for review** |
| In Review | waiting for approval | **Release**, or **Reject** with a reason |
| Released | approved; this revision is fixed | **Start revision B** (the next one) |
| Obsolete | its file left the source folder | comes back In Work if the file returns |

- An assembly can't be released until everything it contains is Released. The window lists
  what still blocks it.
- **Release with everything it contains** does that in one step. It releases every part and
  subassembly in the assembly that isn't Released yet, parts first, and the assembly last.
  Items In Work are submitted and released together. **Submit with everything it contains**
  moves them all to In Review instead, for a team that reviews first. Both show the list
  before anything changes, and both are all or nothing: if one item can't move, none do.
- Importing keeps the states. If an item changes, or something it contains changes, it goes
  back to In Work. If it was Released, its next revision starts (A to B).
- Each change records who, when and the comment, and is a Git commit. Each release is also a
  Git tag, so a release can always be got back exactly: **Get this release…** in the window,
  or `vault get <vault> <item> <revision> <folder>`.
- Each change records the account you are logged in as (for example `PC-NAME\bob`).

## Roles

A vault can say who may release. `roles.json` names:

- **Admins**, who change the roles;
- **Approvers**, who release and reject;
- whether **four-eyes** is on: an approver then can't release something they submitted.

Anyone can still submit and start a new revision. A vault without roles is open: anyone can
release. The first person to add an approver or admin becomes the vault's first admin, and a
vault always keeps at least one admin.

In the window, open **Roles** under the vault's list. From the command line:

```bash
python -m sw2sc vault roles "D:\Vault" add-approver "PC-NAME\jane"
```

```bash
python -m sw2sc vault roles "D:\Vault" four-eyes on
```

`vault roles <vault>` alone shows the roles and yours.

Roles guard against mistakes, not against someone determined. Anyone who can write the
vault's files can edit them, though Git history shows the change.

From the command line:

```bash
python -m sw2sc vault status "D:\Vault"
```

```bash
python -m sw2sc vault submit "D:\Vault" Bracket -m "ready for checking"
```

```bash
python -m sw2sc vault release "D:\Vault" Bracket -m "approved"
```

```bash
python -m sw2sc vault release-all "D:\Vault" Frame -m "first build" --dry-run
```

`reject` (needs `-m`), `revise` and `submit-all` work the same way. Leave out `--dry-run` to
make the change. `vault status <vault> <item>` shows one
item's history and releases.

## What the vault holds

| In the source | In the vault |
|---|---|
| `Bracket.SLDPRT` | `Bracket.sldprt.solidcraft`: a design with the part's solids, properties and feature tree |
| `Frame.SLDASM` | `Frame.sldasm.solidcraft`: a design whose parts and subassemblies are linked to their own designs |
| any other file (drawings, PDF, STEP, pictures) | copied unchanged |
| the SolidWorks files themselves | copied unchanged, unless `--no-originals` |
| folders | mirrored |

The source extension stays in each design's name, so `Bracket.SLDPRT` and `Bracket.SLDASM`
can't overwrite each other.

**Links.** An assembly design uses SolidCraft's own link format, the one Insert Design
writes: a path relative to the assembly and the SHA-256 of the linked design file. A part
used by ten assemblies is stored once. Opened in SolidCraft, every link is found, and
**Update Links** reads the linked designs again. This was checked with SolidCraft 0.40.1.

**Subassemblies.** A subassembly is linked to its own design too. As with SolidCraft's Insert
Design, a linked subassembly is one component. Its geometry is a STEP assembly that places
each of its parts. Assemblies are imported bottom-up, so each subassembly's design exists
before an assembly links to it. Hidden and suppressed instances inside a subassembly are left
out of its geometry.

**Index.** `vault.json` lists every design with:

- its source file and the SHA-256 of that file;
- its part number, revision, description, material and configurations;
- what it uses (with quantities) and where it is used;
- the conversion's warnings, or why it failed.

`VAULT.md` is the same list as a table, for reading.

## Not yet

- In SolidCraft, a linked subassembly shows as one part: its parts aren't separate
  components in the Browser or in SolidCraft's bill of materials. `vault bom` and
  `vault where-used` still list them. SolidCraft PR 14860 (open) adds linked subassemblies
  that keep their components.
- Roles are checked by this tool, not enforced by the file system or a server (see Roles).
- SolidCraft itself doesn't know about these states yet. Upstream, versioning waits for the
  maintainers' decision.
- Only SolidWorks files are converted. Other CAD files are copied unchanged.
