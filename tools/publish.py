"""Publish safely: copy the repository into a clone of the public repository with personal names
replaced, and check that nothing personal is left.

    python tools/publish.py check [PATH ...]          # scan files (default: this repo's tracked files)
    python tools/publish.py export DEST [--rev REV]   # write REV's files into DEST, then check DEST

`export` changes only DEST's working tree: review the result there (GitHub Desktop, `git diff`) and
commit and push it yourself. Nothing is committed or pushed by this tool.

What counts as personal is kept outside the repository, in a private folder (`SW2SC_PRIVATE`, or
`~/.sw2sc-private`), never committed:

    aliases.json   {"a private part name": "Part A", ...}: each name is written as its alias. New
                   names found through folders.txt are added with the next free alias, so an alias
                   never changes once published.
    terms.txt      words that must never appear (a person's name, a client, a project), one per
                   line; `#` starts a comment. Matched without regard to case.
    folders.txt    folders holding your own SolidWorks files, one per line. A file name from them
                   written with its extension (`Gizmo-Q7 Holder.SLDPRT`) is replaced by an alias.
    public_folders.txt   folders of third-party samples (already public): their file names are not
                   private, even where a file of yours has the same name, except under a folder of
                   folders.txt inside them (the more specific folder wins).
    allow.txt      names that may be published as they are (a generic name such as `Bracket`).
    reserved.txt   aliases published before that no longer stand for a name: never given again.

Whatever the private folder holds, `check` also fails on: paths into a user's home folder or a
cloud-synced folder, and e-mail addresses (other than no-reply and example addresses).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAD_EXT = ("sldprt", "sldasm", "slddrw")
TEXT_EXT = (".py", ".rs", ".md", ".txt", ".toml", ".json", ".yml", ".yaml", ".ps1", ".cmd", ".html", ".lock", ".wit",
            ".cfg", ".ini", "")

# found whatever the private folder says (no personal data here: only the shapes of it)
BUILT_IN = [
    ("a path into a user's home folder", re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|Default\b|<|\{|\$|%)[^\\/\s'\"<>|]+", re.I)),
    ("a path into a user's home folder", re.compile(r"(?<![\w.])/(?:home|Users)/(?!<|\{|\$)[A-Za-z0-9_.-]+/")),
    ("a path into a cloud-synced folder", re.compile(r"[\\/](?:Dropbox|OneDrive(?: - [^\\/]+)?|Google Drive|iCloud Drive)[\\/]", re.I)),
    ("an e-mail address", re.compile(r"(?<![\w.+-])[\w.+-]+@(?!(?:[\w-]+\.)*(?:example\.(?:com|org|net)|users\.noreply\.github\.com|anthropic\.com)\b)"
                                     r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
]


def private_dir() -> str:
    return os.environ.get("SW2SC_PRIVATE") or os.path.join(os.path.expanduser("~"), ".sw2sc-private")


def _lines(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    out = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.split("#", 1)[0].strip()
        if ln:
            out.append(ln)
    return out


def load_private(pdir: str | None = None) -> dict:
    pdir = pdir or private_dir()
    ap = os.path.join(pdir, "aliases.json")
    aliases = json.load(open(ap, encoding="utf-8")) if os.path.exists(ap) else {}
    return {"dir": pdir, "aliases": aliases, "terms": _lines(os.path.join(pdir, "terms.txt")),
            "folders": _lines(os.path.join(pdir, "folders.txt")),
            "public_folders": _lines(os.path.join(pdir, "public_folders.txt")),
            "allow": _lines(os.path.join(pdir, "allow.txt")),
            "reserved": _lines(os.path.join(pdir, "reserved.txt"))}


def _cad_names(top: str, skip: list[str]) -> set[str]:
    names = set()
    skip = [os.path.normcase(os.path.abspath(x)) for x in skip]
    for root, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if os.path.normcase(os.path.abspath(os.path.join(root, d))) not in skip]
        for fn in files:
            base, ext = os.path.splitext(fn)
            if ext[1:].lower() in CAD_EXT and len(base) >= 2:
                names.add(base)
    return names


def own_names(priv: dict) -> dict[str, tuple[str, bool]]:
    """Every SolidWorks file name known (lower case -> (the name, whether it is private)): yours,
    under the private folders, are private unless a public sample folder (outside any private
    folder within it) has the same name, or it is allowed. Alias-shaped names are never private."""
    out = {}
    for top in priv.get("public_folders", []):
        for n in _cad_names(top, priv["folders"]):
            out[n.lower()] = (n, False)
    allowed = {a.lower() for a in priv.get("allow", [])}
    for top in priv["folders"]:
        for n in _cad_names(top, []):
            k = n.lower()
            if k not in out:
                out[k] = (n, k not in allowed and not re.fullmatch(r"part [a-z]+\d*", k))
    return out


def _file_name(cand: str, names: dict) -> tuple[str, bool] | None:
    """The known file name `cand` ends with: its tails from each word start, longest first; the
    first that is a known name decides (so `Rocker Arm Cylinder` is that file, not `Cylinder`)."""
    for m in re.finditer(r"(?:^|(?<=[\s(\[{,;]))\S", cand):
        hit = names.get(cand[m.start():].strip().lower())
        if hit:
            return hit
    return None


def next_alias(used: set[str]) -> str:
    n = 0
    while True:
        k, s = n, ""
        while True:
            s = chr(65 + k % 26) + s
            k = k // 26 - 1
            if k < 0:
                break
        if f"Part {s}" not in used:
            return f"Part {s}"
        n += 1


def _word(name: str) -> re.Pattern:
    # the name on its own, not inside a longer word (an alias for "Wheel" must not touch "Flywheel")
    return re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])", re.I)


def scrub(text: str, aliases: dict, roots: list[tuple[str, str]]) -> str:
    """`text` with the given paths and every private name replaced, longest name first."""
    for path, rep in roots:
        parts = [re.escape(x) for x in re.split(r"[\\/]+", path) if x]
        text = re.sub(r"[\\/]+".join(parts), rep, text, flags=re.I)
    for name in sorted(aliases, key=len, reverse=True):
        text = _word(name).sub(aliases[name], text)
    return text


FILE_REF = re.compile(r"([^\\/|:*?\"<>\r\n`]{1,120}?)\.(?:sldprt|sldasm|slddrw)\b", re.I)


def find_new(text: str, names: dict, aliases: dict) -> list[str]:
    """Private file names written with their extension in `text` that have no alias yet."""
    known = {k.lower() for k in aliases}
    found = []
    for m in FILE_REF.finditer(text):
        hit = _file_name(m.group(1), names)
        if hit and hit[1] and hit[0].lower() not in known:
            found.append(hit[0])
            known.add(hit[0].lower())
    return found


def check_text(text: str, terms: list[str], names: dict | None = None) -> list[tuple[int, str, str]]:
    """(line, what, the text found) for everything personal in `text`."""
    out = []
    term_res = [(t, _word(t)) for t in terms]
    for i, line in enumerate(text.splitlines(), 1):
        for what, rx in BUILT_IN:
            for m in rx.finditer(line):
                out.append((i, what, m.group(0)))
        for t, rx in term_res:
            if rx.search(line):
                out.append((i, "a private term", t))
        if names:
            for m in FILE_REF.finditer(line):
                hit = _file_name(m.group(1), names)
                if hit and hit[1]:
                    out.append((i, "a private file name", hit[0]))
    return out


def _is_text(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in TEXT_EXT


def _read(path: str) -> str | None:
    try:
        return open(path, encoding="utf-8").read()
    except (UnicodeDecodeError, OSError):
        return None


def check_paths(paths: list[str], priv: dict) -> int:
    names = own_names(priv)
    terms = priv["terms"] + sorted(priv["aliases"])
    bad = 0
    for p in paths:
        if not _is_text(p):
            continue
        s = _read(p)
        if s is None:
            continue
        for i, what, found in check_text(s, terms, names):
            bad += 1
            print(f"{p}:{i}: {what}: {found!r}")
    return bad


def tracked(root: str) -> list[str]:
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, check=True).stdout
    return [os.path.join(root, p) for p in out.decode("utf-8").split("\0") if p]


def export(dest: str, rev: str, priv: dict) -> int:
    if not os.path.isdir(os.path.join(dest, ".git")):
        sys.exit(f"{dest} is not a git clone (export writes into a clone of the public repository)")
    data = subprocess.run(["git", "-C", ROOT, "archive", "--format=tar", rev], capture_output=True, check=True).stdout
    names = own_names(priv)
    aliases = dict(priv["aliases"])
    home = os.path.expanduser("~")
    roots = [(ROOT, "<repo>"), (os.path.join(home, "Documents"), "<parts folder>"), (home, "<home>")]
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf.getmembers():
            if m.isfile():
                files[m.name] = tf.extractfile(m).read()
    # new private names first, so every file gets the same aliases
    for name, raw in files.items():
        if _is_text(name):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for n in find_new(text, names, aliases):
                aliases[n] = next_alias(set(aliases.values()) | set(priv.get("reserved", [])))
    if aliases != priv["aliases"]:
        os.makedirs(priv["dir"], exist_ok=True)
        json.dump(aliases, open(os.path.join(priv["dir"], "aliases.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(f"{len(aliases) - len(priv['aliases'])} new aliases kept in {priv['dir']}")
    # the public tree becomes the export: files it has that the export hasn't are removed
    keep = set(files)
    for p in tracked(dest):
        rel = os.path.relpath(p, dest).replace(os.sep, "/")
        if rel not in keep and os.path.exists(p):
            os.remove(p)
    for name, raw in files.items():
        out = os.path.join(dest, *name.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if _is_text(name):
            try:
                raw = scrub(raw.decode("utf-8"), aliases, roots).encode("utf-8")
            except UnicodeDecodeError:
                pass
        with open(out, "wb") as fh:
            fh.write(raw)
    print(f"wrote {len(files)} files from {rev} into {dest}")
    priv = dict(priv, aliases=aliases)
    return check_paths([os.path.join(dest, *n.split("/")) for n in files], priv)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="scan files for personal data")
    c.add_argument("paths", nargs="*")
    e = sub.add_parser("export", help="write the repository into a public clone, names replaced, then check it")
    e.add_argument("dest")
    e.add_argument("--rev", default="HEAD")
    a = ap.parse_args(argv)
    priv = load_private()
    if not os.path.isdir(priv["dir"]):
        print(f"(no private folder at {priv['dir']}: only the built-in checks run)")
    if a.cmd == "check":
        paths = []
        for p in a.paths or [ROOT]:
            if os.path.isdir(p):
                paths += tracked(p) if os.path.isdir(os.path.join(p, ".git")) or p == ROOT else \
                    [os.path.join(r, f) for r, _d, fs in os.walk(p) for f in fs]
            else:
                paths.append(p)
        bad = check_paths(paths, priv)
    else:
        bad = export(a.dest, a.rev, priv)
    print("nothing personal found" if not bad else f"{bad} personal item(s) found: fix them before publishing")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
