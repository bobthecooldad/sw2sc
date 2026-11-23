"""Write the project's version (the VERSION file) into the plugin's manifest and crates, so the
plugin, its release and the converter all carry one number. Run by build.ps1 and the CI build."""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
version = open(os.path.join(HERE, "..", "VERSION"), encoding="utf-8").read().strip()
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    raise SystemExit(f"VERSION is not x.y.z: {version!r}")
manifest = os.path.join(HERE, "package", "sw2sc", "plugin.json")
m = json.load(open(manifest, encoding="utf-8"))
m["version"] = version
with open(manifest, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(m, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
cargo = os.path.join(HERE, "Cargo.toml")
s = open(cargo, encoding="utf-8").read()
s = re.sub(r'(\[workspace\.package\][^\[]*?\nversion = ")[^"]*(")', rf"\g<1>{version}\g<2>", s, count=1)
open(cargo, "w", encoding="utf-8", newline="\n").write(s)
print(version)
