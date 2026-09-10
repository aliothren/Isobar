"""O19 optional item (C63-d): express links -- the price curve of
hub-insensitivity.

Pre-registration: FIXLIST O19 batch block, OPTIONAL ITEM (family and
skip locked, calibers, wire-price arithmetic, the two-handed 3x3 risk
-- all filed before this script existed).

THE CURVE: x = declared wire price (x mesh), y = the corner/centre
hub lever (busiest-load ratio on uniform hub-rooted flows), points =
{mesh, express(s), torus, switch} on two hosts (3x3 macro -- the
pinned 5/3 lever's home -- and the 6x8 die grid). A7 ended with two
antidotes (torus: fold x2; switch: N^2); express prices the spectrum
between.

    python3 scripts/analyze_express.py     (container)
      -> analysis/express_weave.json + .md + express_price_curve.png
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import fabric, interconnect as ic, placement

OUT = "/home/workspace/analysis"
DOWN, UP = 1.0, 0.5


def busiest(obj, n):
    load = {}
    for i in range(n):
        for vol, (a, b) in ((DOWN, (ic.HUB, i)), (UP, (i, ic.HUB))):
            for r, tag in obj.path_directed(a, b):
                key = f"{r}/{tag}"
                load[key] = load.get(key, 0.0) + vol
    return max(load.values()) if load else 0.0


def mesh_wire(w, h):
    return (w - 1) * h + w * (h - 1)          # unit grid edges


def express_wire(w, h, s):
    add = max(w - s, 0) * h * s + max(h - s, 0) * w * s
    return mesh_wire(w, h) + add


def switch_wire(slots):
    n = len(slots)
    d = [abs(a[0] - b[0]) + abs(a[1] - b[1])
         for i, a in enumerate(slots) for b in slots[i + 1:]]
    return sum(d)                              # N^2-class pairwise proxy


def host(slots, grid_wh, skips):
    w, h = grid_wh
    w0 = mesh_wire(w, h)
    rows = {}

    def lever(build):
        c = busiest(build("center"), len(slots))
        k = busiest(build("corner"), len(slots))
        return k / c, c, k

    rows["mesh"] = {"wire_x": 1.0, **dict(zip(
        ("lever", "busiest_center", "busiest_corner"),
        lever(lambda hub: ic.Mesh(slots, {"routing": "xy", "hub": hub}))))}
    for s in skips:
        rows[f"express_s{s}"] = {
            "wire_x": express_wire(w, h, s) / w0, **dict(zip(
                ("lever", "busiest_center", "busiest_corner"),
                lever(lambda hub, s=s: ic.Express(
                    slots, {"routing": "xy", "hub": hub, "skip": s}))))}
    rows["torus"] = {"wire_x": 2.0, **dict(zip(
        ("lever", "busiest_center", "busiest_corner"),
        lever(lambda hub: ic.Torus(slots, {"routing": "xy", "hub": hub}))))}
    sw = busiest(ic.Switch(slots, {}), len(slots))
    rows["switch"] = {"wire_x": switch_wire(slots) / w0, "lever": 1.0,
                      "busiest_center": sw, "busiest_corner": sw}
    return rows


def main():
    s33 = placement.sequential_fill(
        fabric.from_yaml("/home/workspace/models/fabric/mlx300_3x3.yaml")
    ).slots["macro"]
    import scripts.analyze_d2d as d2d
    s48 = placement.sequential_fill(fabric.from_yaml(d2d.MULTI)).slots["die"]

    hosts = {"3x3_macro": host(s33, (3, 3), [2]),
             "6x8_die": host(s48, (6, 8), [2, 3, 4])}

    out = {"hosts": hosts,
           "caliber": ("y = corner/centre busiest-load lever on uniform "
                       "hub-rooted flows (down 1.0 / up 0.5); x = declared "
                       "wire price relative to mesh (express: +addable "
                       "links x s; torus: x2 fold; switch: the pairwise "
                       "N^2 proxy); physical hops of express == Manhattan "
                       "== mesh, asserted in group 48")}
    with open(os.path.join(OUT, "express_weave.json"), "w") as f:
        json.dump(out, f, indent=1)

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.2))
    for ax, (hname, rows) in zip(axes, hosts.items()):
        for name, r in rows.items():
            mark = {"mesh": "s", "torus": "^", "switch": "D"}.get(
                name.split("_")[0], "o")
            ax.scatter(r["wire_x"], r["lever"], s=70, marker=mark,
                       color="#d1495b" if "express" in name else "#2a9d8f"
                       if name == "torus" else "#8fa8bf")
            ax.annotate(name.replace("express_", "express "),
                        (r["wire_x"], r["lever"]),
                        textcoords="offset points", xytext=(6, 5),
                        fontsize=8)
        ax.axhline(1.0, color="#555", lw=0.6, ls=":")
        ax.set_xscale("log")
        ax.set_xlabel("declared wire price (x mesh)")
        ax.set_title(hname)
    axes[0].set_ylabel("corner/centre hub lever (1.0 = insensitive)")
    fig.suptitle("The price curve of hub-insensitivity "
                 "(mesh -> express -> torus -> switch)", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "express_price_curve.png"), dpi=160)

    L = ["# Express links: the price curve (O19 optional, C63-d; post-v6)",
         "", "| host | weave | wire price (x mesh) | lever | busiest c/k |",
         "|---|---|---|---|---|"]
    for hname, rows in hosts.items():
        for name, r in rows.items():
            L.append(f"| {hname} | {name} | {r['wire_x']:.2f} "
                     f"| {r['lever']:.3f} | {r['busiest_center']:.1f} / "
                     f"{r['busiest_corner']:.1f} |")
    L += ["", out["caliber"], "",
          "![price curve](express_price_curve.png)", ""]
    with open(os.path.join(OUT, "express_weave.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    for hname, rows in hosts.items():
        print(hname)
        for name, r in rows.items():
            print(f"  {name:12} wire {r['wire_x']:6.2f}x  lever "
                  f"{r['lever']:.3f}  busiest {r['busiest_center']:.1f}/"
                  f"{r['busiest_corner']:.1f}")


if __name__ == "__main__":
    main()
