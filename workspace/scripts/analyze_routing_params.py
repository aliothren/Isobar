"""O19 conditional item B (C63-f): routing-algorithm params -- the readout.

Pre-registration: FIXLIST O19 batch block, ITEM B. The occupancy-side
completeness debt: replies that RETRACE the request route (the standing
default) vs YX replies (the common real-NoC form -- up load lands on
segments the down route never uses), plus o1turn (balanced dimension
order, the declared parity rule). Defaults are byte-neutral (gate: the
full suite, zero pins moved).

EXPECTATIONS (pre-written, two-handed): the down side never moves with
the reply choice; YX replies relieve the busiest wire ONLY where the UP
side binds (psum-weighted up, x2) and change nothing where the down
side binds (up at 0.5) -- the debt pays exactly where partial sums
dominate.

Uniform hub-rooted flows (down 1.0 / up w), hosts 2x4 and 3x3 (hub
center), w in {0.5, 2.0}; variants: xy+retrace (the pinned baseline),
xy+yx-reply, o1turn+retrace, o1turn+yx.

    python3 scripts/analyze_routing_params.py     (container)
      -> analysis/routing_params.json + .md + routing_params.png
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts import fabric, interconnect as ic, placement

OUT = "/home/workspace/analysis"
VARIANTS = [("xy + retrace", {"routing": "xy", "reply": "retrace"}),
            ("xy + yx reply", {"routing": "xy", "reply": "yx"}),
            ("o1turn + retrace", {"routing": "o1turn", "reply": "retrace"}),
            ("o1turn + yx reply", {"routing": "o1turn", "reply": "yx"})]


def busiest(obj, n, up_w):
    load = {}
    for i in range(n):
        for vol, (a, b) in ((1.0, (ic.HUB, i)), (up_w, (i, ic.HUB))):
            for r, tag in obj.path_directed(a, b):
                key = f"{r}/{tag}"
                load[key] = load.get(key, 0.0) + vol
    down = {k: v for k, v in load.items()}
    return max(load.values()), max(load, key=load.get)


def main():
    hosts = {"2x4": placement.sequential_fill(fabric.default()).slots["macro"],
             "3x3": placement.sequential_fill(fabric.from_yaml(
                 "/home/workspace/models/fabric/mlx300_3x3.yaml")
             ).slots["macro"]}
    out = {"rows": {}}
    for hname, slots in hosts.items():
        for w in (0.5, 2.0):
            for label, extra in VARIANTS:
                m = ic.Mesh(slots, {"hub": "center", **extra})
                b, res = busiest(m, len(slots), w)
                out["rows"][f"{hname}|up{w}|{label}"] = {
                    "busiest": b, "resource": res}

    # PATTERN 2 (added after the hub-rooted refutation, recorded in the
    # item record): NODE-TO-NODE all-pairs uniform -- distributed
    # endpoints, the reply/o1turn knobs' real habitat (at a sink the
    # incident-segment funnel is conservation-fixed and routing cannot
    # move it; between distributed pairs the middle segments CAN be
    # rerouted).
    for hname, slots in hosts.items():
        n = len(slots)
        for label, extra in VARIANTS:
            m = ic.Mesh(slots, {"hub": "center", **extra})
            load = {}
            for a in range(n):
                for b in range(n):
                    if a == b:
                        continue
                    for r, tag in m.path_directed(a, b):
                        key = f"{r}/{tag}"
                        load[key] = load.get(key, 0.0) + 1.0
            out["rows"][f"{hname}|allpairs|{label}"] = {
                "busiest": max(load.values()),
                "resource": max(load, key=load.get)}

    # PATTERN 3: the adversarial permutation (i -> n-1-i), o1turn's classic
    # habitat -- worst-case single-order traffic.
    for hname, slots in hosts.items():
        n = len(slots)
        for label, extra in VARIANTS:
            m = ic.Mesh(slots, {"hub": "center", **extra})
            load = {}
            for a in range(n):
                b = n - 1 - a
                if a == b:
                    continue
                for r, tag in m.path_directed(a, b):
                    key = f"{r}/{tag}"
                    load[key] = load.get(key, 0.0) + 1.0
            out["rows"][f"{hname}|mirror|{label}"] = {
                "busiest": max(load.values()),
                "resource": max(load, key=load.get)}

    # the pre-written checks
    checks = {}
    for hname in hosts:
        base_l = out["rows"][f"{hname}|up0.5|xy + retrace"]["busiest"]
        yx_l = out["rows"][f"{hname}|up0.5|xy + yx reply"]["busiest"]
        base_h = out["rows"][f"{hname}|up2.0|xy + retrace"]["busiest"]
        yx_h = out["rows"][f"{hname}|up2.0|xy + yx reply"]["busiest"]
        checks[hname] = {
            "down_bound_unmoved_at_up0.5": yx_l == base_l,
            "relief_at_up2.0": yx_h < base_h,
            "relief_ratio_up2.0": base_h / yx_h if yx_h else None}
    for hname in hosts:
        xy = out["rows"][f"{hname}|allpairs|xy + retrace"]["busiest"]
        best = min(out["rows"][f"{hname}|allpairs|{l}"]["busiest"]
                   for l, _ in VARIANTS)
        checks[hname]["allpairs_relief_ratio"] = xy / best
    out["checks"] = checks
    out["invariant"] = ("hub-rooted (sink-convergent) patterns are "
                        "ROUTING-INVARIANT on the busiest wire: the "
                        "sink's incident-segment funnel is fixed by "
                        "conservation; reply order and o1turn pay only "
                        "on distributed node-to-node patterns")
    with open(os.path.join(OUT, "routing_params.json"), "w") as f:
        json.dump(out, f, indent=1)

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.0), sharey=False)
    for ax, hname in zip(axes, hosts):
        labels = [v[0] for v in VARIANTS]
        x = np.arange(len(labels))
        for off, w, col in ((-0.18, 0.5, "#8fa8bf"), (0.18, 2.0, "#d1495b")):
            ys = [out["rows"][f"{hname}|up{w}|{l}"]["busiest"]
                  for l in labels]
            ax.bar(x + off, ys, width=0.34, color=col, label=f"up weight {w}")
            for xi, y in zip(x + off, ys):
                ax.text(xi, y + 0.06, f"{y:g}", ha="center", fontsize=7)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=7, rotation=12)
        ax.set_title(hname)
    axes[0].set_ylabel("busiest directed wire load")
    axes[0].legend(fontsize=8)
    fig.suptitle("Routing params: the sink-funnel invariant -- reply order "
                 "cannot move a busiest wire", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "routing_params.png"), dpi=160)

    L = ["# Routing-algorithm params (O19 item B, C63-f; post-v6)", "",
         "| host | up weight | variant | busiest | resource |",
         "|---|---|---|---|---|"]
    for key, r in out["rows"].items():
        h, w, l = key.split("|")
        L.append(f"| {h} | {w[2:]} | {l} | {r['busiest']:g} "
                 f"| `{r['resource']}` |")
    L += ["", "Checks: " + json.dumps(checks), "",
          "![routing params](routing_params.png)", ""]
    with open(os.path.join(OUT, "routing_params.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    for k, v in out["rows"].items():
        print(f"{k:34} busiest {v['busiest']:g}  {v['resource']}")
    print("checks:", checks)


if __name__ == "__main__":
    main()
