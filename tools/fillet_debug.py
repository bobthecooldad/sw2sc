"""Step through a part's fillets and chamfers against its own solid (F-032).

    python tools/fillet_debug.py PART.SLDPRT

Builds the design up to each fillet or chamfer, lists the edge sets that fit and evaluates
each (both sides for a one-sided chamfer), next to the reference solid's volume and area.
Follows the first candidate of each step.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sw2sc import features, fillets, solidcraft, verify  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402


def show(r):
    if not r:
        return "no result"
    return f"volume {r['volume'] and round(r['volume'], 3)}  area {r['area'] and round(r['area'], 3)}  {r['errors'][:1]}"


def main(path):
    cli = verify.find_cli()
    tmp = tempfile.mkdtemp(prefix="sw2sc-fd-")
    feats = features.read(SwFile(path))
    print("features:", [(f.kind, f.name) for f in feats])
    ref, _ = solidcraft.convert(path, feature_tree=False)
    q = os.path.join(tmp, "ref.solidcraft")
    json.dump(ref, open(q, "w"))
    print("reference:", show(verify.evaluate(cli, q)))
    # extrude directions: the first set under which the first fillet's edges fit
    import itertools
    extr = [f for f in feats if f.kind in ("boss", "cut")]
    choices = {}
    first = next((f for f in feats if f.kind in ("fillet", "chamfer")), None)
    for n, combo in enumerate(itertools.product(["positive", "negative", "symmetric"], repeat=len(extr))):
        if n >= 60 or first is None:
            break
        c = {f.name: (dc, None) for f, dc in zip(extr, combo)}
        d = features.design("t", feats, c, None, True, {})
        d.pop("pending", None)
        if fillets.candidates(d, first, feats, cli, tmp):
            choices = c
            print("directions:", combo)
            break
    picked = {}
    while True:
        d = features.design("t", feats, choices, None, True, picked)
        pending = d.pop("pending", None)
        q = os.path.join(tmp, "d.solidcraft")
        json.dump(d, open(q, "w"))
        print(f"\nbefore {pending or 'the end'}:", show(verify.evaluate(cli, q)))
        if not pending:
            return
        f = next(x for x in feats if x.name == pending)
        cs = fillets.candidates(d, f, feats, cli, tmp, picked.get(""))
        print(f"{pending}: {len(f.edges)} edges, {len(cs)} edge sets fit")
        for edges, amaps in cs[:6]:
            for flip in (False, True) if f.kind == "chamfer" else (False,):
                t = dict(picked, **{pending: edges, "": amaps, "flip:" + pending: flip})
                e = features.design("t", feats, choices, None, True, t)
                e.pop("pending", None)
                json.dump(e, open(q, "w"))
                print("   ", "flip" if flip else "    ", show(verify.evaluate(cli, q)), [n for _m, n in edges][:3])
        if not cs:
            return
        picked = dict(picked, **{pending: cs[0][0], "": cs[0][1]})


if __name__ == "__main__":
    main(sys.argv[1])
