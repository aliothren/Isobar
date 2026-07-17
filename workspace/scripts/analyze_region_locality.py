"""Region-placement locality under the ADOPTED metric (volume-weighted all-pair
Manhattan), replacing the nearest-neighbour figure.

This is the committed source of the 17.8% number and of
analysis/region_locality_vw.png. It reuses io_study's deterministic floorplan
(die_floorplan/die_locality) -- same placements, same dataflow edges -- and only
changes the metric: NN-min flatters adjacency (two regions touching at one corner
score distance 1 regardless of traffic), so we score every producer core against
every consumer core, volume-weighted.

Two stages, because the host python has io_study but no matplotlib and the
container has matplotlib but no io_study mount:

    python3 analyze_region_locality.py compute   # on the HOST (repo root)
    python3 analyze_region_locality.py plot      # in the CONTAINER
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "..", "analysis", "region_locality.json")
PNG_PATH = "/home/workspace/analysis/region_locality_vw.png"


def vw_allpair(a, b):
    """Mean Manhattan distance over ALL (producer cell, consumer cell) pairs."""
    ds = [abs(ma - mb) + abs(ca - cb) for (ma, ca) in a for (mb, cb) in b]
    return sum(ds) / len(ds)


def compute():
    sys.path.insert(0, os.path.join(HERE, "..", "..", "io_study", "scripts"))
    from die_locality import (region_cells, nn_distance, DATAFLOW,
                              SIZE_ORDER, DATAFLOW_ORDER)

    out = {"edges": [f"{p}->{c}" for p, c, _ in DATAFLOW],
           "volumes": [v for _, _, v in DATAFLOW], "orders": {}}
    for order, name in ((SIZE_ORDER, "size order"),
                        (DATAFLOW_ORDER, "dataflow order")):
        cells = region_cells(order)
        vw = [vw_allpair(cells[p], cells[c]) for p, c, _ in DATAFLOW]
        nn = [nn_distance(cells[p], cells[c]) for p, c, _ in DATAFLOW]
        out["orders"][name] = {
            "vw_dist": vw, "nn_dist": nn,
            "vw_total": sum(d * v for d, (_, _, v) in zip(vw, DATAFLOW)),
            "nn_total": sum(d * v for d, (_, _, v) in zip(nn, DATAFLOW)),
        }
    s, d = out["orders"]["size order"], out["orders"]["dataflow order"]
    out["vw_drop_pct"] = 100 * (1 - d["vw_total"] / s["vw_total"])
    out["nn_drop_pct"] = 100 * (1 - d["nn_total"] / s["nn_total"])
    with open(JSON_PATH, "w") as f:
        json.dump(out, f, indent=1)
    print(f"vw drop {out['vw_drop_pct']:.1f}%  (nn would read {out['nn_drop_pct']:.1f}%)")
    print(f"JSON -> {JSON_PATH}")


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with open("/home/workspace/analysis/region_locality.json") as f:
        d = json.load(f)
    edges, orders = d["edges"], d["orders"]
    x = range(len(edges))
    w = 0.38

    plt.rcParams.update({"font.size": 13, "axes.titlesize": 14})
    plt.figure(figsize=(9.5, 5))
    for i, (name, color) in enumerate([("size order", "tab:red"),
                                       ("dataflow order", "tab:green")]):
        o = orders[name]
        plt.bar([xx + (i - 0.5) * w for xx in x], o["vw_dist"], width=w,
                color=color, alpha=0.85,
                label=f"{name}  ($\\Sigma$ vol$\\times$dist = {o['vw_total']:.2e})")
    plt.xticks(list(x), edges, rotation=20, ha="right")
    plt.ylabel("volume-weighted mean distance (hops)")
    plt.title(f"Producer$\\to$consumer locality, volume-weighted all-pair metric\n"
              f"(dataflow order lowers the total by {d['vw_drop_pct']:.1f}%)")
    plt.grid(axis="y", alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(PNG_PATH, dpi=120)
    print(f"PNG -> {PNG_PATH}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "compute"
    compute() if mode == "compute" else plot()
