"""S8-D: cheap tie-breaker features on the floor-tied endpoints, read from
the same load map the maximum comes from (resource_loads). Decide by
discrimination first. See FIXLIST S8-D.

    python3 scripts/tie_features.py -> analysis/tie_features.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import b3_booksim_cost_probe as pr
from scripts import kappa_geometry_sweep as kg
from scripts import search_eval as se
from scripts import search_space as ss

OUT = os.path.join(se.A, "tie_features.json")


def features(W, pi, near=0.10):
    fls = kg.flows_by_boundary(W, pi)
    tot_link, n_near, second, n_at_max, busiest = 0.0, 0, 0.0, 0, 0.0
    for fl in fls:
        load = se.resource_loads(fl, W.die_ic)
        links = [v for k, v in load.items() if k[0] != "port"]
        mx = max(load.values())
        vals = sorted(load.values(), reverse=True)
        tot_link += sum(links)
        n_near += sum(1 for v in load.values() if v >= (1 - near) * mx)
        n_at_max += sum(1 for v in load.values() if abs(v - mx) < 1e-9 * mx)
        second += vals[1] if len(vals) > 1 else 0.0
        busiest += mx
    return {"busiest_sum": busiest, "total_link_occupancy": tot_link,
            "n_resources_within_10pct_of_max": n_near,
            "n_resources_at_max": n_at_max, "second_busiest_sum": second}


def spearman(a, b):
    def rk(x):
        o = sorted(range(len(x)), key=lambda i: x[i])
        r = [0] * len(x)
        for k, i in enumerate(o):
            r[i] = k
        return r
    ra, rb = rk(a), rk(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    d = ((sum((x - ma) ** 2 for x in ra) ** 0.5) * (sum((y - mb) ** 2 for y in rb) ** 0.5))
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / d if d else float("nan")


def main():
    out = {"note": __doc__.strip(), "item3_tie_set": {}, "A_endpoints": {}}
    # (1) the item-3 shrunk instance: four floor-tied endpoints with a known BookSim order
    Ws = pr.shrunk_workload()
    b3 = json.load(open(os.path.join(se.A, "b3_shrunk_rerank.json")))["rows"]
    names = [n for n in b3 if n.startswith("sa_")]
    for n in names:
        pi = ss.Pi.from_json(b3[n]["pi"])
        f = features(Ws, pi)
        f["booksim_cycles_total"] = b3[n]["booksim_cycles_total"]
        out["item3_tie_set"][n] = f
    book = [out["item3_tie_set"][n]["booksim_cycles_total"] for n in names]
    print("item-3 floor-tied endpoints (BookSim total cycles ascending = better):")
    for n in sorted(names, key=lambda n: out["item3_tie_set"][n]["booksim_cycles_total"]):
        f = out["item3_tie_set"][n]
        print(f"  {n:24} BookSim {f['booksim_cycles_total']:7d} | busiest sum "
              f"{f['busiest_sum']/1e6:7.2f}M | total link occ {f['total_link_occupancy']/1e6:8.2f}M "
              f"| n within 10% of max {f['n_resources_within_10pct_of_max']:3d} | n at max "
              f"{f['n_resources_at_max']:3d} | 2nd-busiest sum {f['second_busiest_sum']/1e6:7.2f}M")
    out["item3_spearman_vs_booksim"] = {
        k: spearman([out["item3_tie_set"][n][k] for n in names], book)
        for k in ("total_link_occupancy", "n_resources_within_10pct_of_max",
                  "n_resources_at_max", "second_busiest_sum")}
    print("  Spearman(feature, BookSim) over the 4:", {k: round(v, 3) for k, v in out["item3_spearman_vs_booksim"].items()})
    # (2) A's nine endpoints (544-die): do the features discriminate at all?
    W = se.Workload2p7B()
    seeds = json.load(open(os.path.join(se.A, "seating_seeds.json")))["cells"]["weak"]["runs"]
    for k, v in seeds.items():
        out["A_endpoints"][k] = features(W, ss.Pi.from_json(v["best_pi"]))
    print("A's nine weak-cell endpoints (all on the floor):")
    for k, f in out["A_endpoints"].items():
        print(f"  {k:14} busiest {f['busiest_sum']/1e6:7.2f}M | total link occ "
              f"{f['total_link_occupancy']/1e6:8.2f}M | n within 10% {f['n_resources_within_10pct_of_max']:4d} "
              f"| n at max {f['n_resources_at_max']:4d} | 2nd {f['second_busiest_sum']/1e6:7.2f}M")
    for k in ("total_link_occupancy", "n_resources_within_10pct_of_max", "second_busiest_sum"):
        vals = [f[k] for f in out["A_endpoints"].values()]
        out[f"A_spread_{k}_pct"] = (max(vals) / min(vals) - 1) * 100 if min(vals) else float("nan")
        print(f"  spread of {k} over the nine: {out[f'A_spread_{k}_pct']:.2f}%")
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
