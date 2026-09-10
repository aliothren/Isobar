"""O19 queued-conditional item A (C63-e): hier_wide -- the fidelity readout.

Pre-registration: FIXLIST O19 batch block, ITEM A (contract, lane rule,
anchor caliber, the two hands). The question the item exists for: the
FlooNoC anchor (80.6 GB/s, post-layout) has so far been POURED INTO A
MESH; on its own structural class (wide multi-channel backbone over a
concentrated local tier), does the reading relax (backbone relief) or
WORSEN (the local gateway funnel binds -- a wide backbone cannot rescue
a concentrated local tier)?

READOUT: ffn1 fixture flows on the 2x4 macro grid (the anchor's home
level), serialization at the FlooNoC anchor bandwidth (per physical
channel, declared): star (floor) / mesh (the poured baseline) /
hier_wide tile [2,2], W in {1, 2, 4}. Plus the uniform-flow load
structure showing WHERE the bottleneck sits per W.

    python3 scripts/analyze_hier_wide.py     (container)
      -> analysis/hier_wide.json + .md + hier_wide_fidelity.png
"""
import dataclasses
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import scripts.crossbar_comm as cc
from scripts import anchors, fabric, interconnect as ic, placement

OUT = "/home/workspace/analysis"
FX = "/home/workspace/tests/fixtures"
ANCHOR_GBPS = 80.6                    # FlooNoC, post-layout; per channel


def _with(topology, params, bw_wc):
    base = fabric.default()
    levels = [dataclasses.replace(
        lv, link=dataclasses.replace(lv.link, topology=topology,
                                     params=params,
                                     bandwidth_words_per_cycle=bw_wc))
        if lv.name == "macro" else lv for lv in base.levels]
    return dataclasses.replace(base, name=f"v-{topology}",
                               levels=levels).validate()


def main():
    wc = anchors.words_per_cycle(ANCHOR_GBPS) if hasattr(
        anchors, "words_per_cycle") else \
        fabric.default().device.words_per_cycle(ANCHOR_GBPS)

    td = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(FX, "ffn1_prefill_map.txt"),
                    os.path.join(td, "timeloop-mapper.map.txt"))
        shutil.copy(os.path.join(FX, "ffn1_prefill_stats.txt"),
                    os.path.join(td, "timeloop-mapper.stats.txt"))
        variants = [("star", "star", {}),
                    ("mesh (poured)", "mesh",
                     {"routing": "xy", "hub": "center"})]
        for W in (1, 2, 4):
            variants.append((f"hier_wide W={W}", "hier_wide",
                             {"routing": "xy", "hub": "center",
                              "concentration": [2, 2], "channels": W}))
        rows = {}
        for label, topo, params in variants:
            fab = _with(topo, params, wc)
            pl = placement.sequential_fill(fab)
            flows, _, _, _ = cc.build_flows(td, fabric=fab, placement=pl,
                                            verbose=False)
            occ = cc.link_occupancy(flows, fab, fab.device.cycle_seconds, pl)
            bo = occ["bottleneck"]
            rows[label] = {"serialization_s": occ["serialization_s"],
                           "bottleneck": bo["resource"],
                           "bottleneck_volume": bo["volume"]}
    finally:
        shutil.rmtree(td, ignore_errors=True)

    star = rows["star"]["serialization_s"]
    for r in rows.values():
        r["x_vs_star"] = r["serialization_s"] / star
    mesh_x = rows["mesh (poured)"]["x_vs_star"]
    native = {W: rows[f"hier_wide W={W}"]["x_vs_star"] for W in (1, 2, 4)}
    all_local = all("rport" in rows[f"hier_wide W={W}"]["bottleneck"]
                    for W in (1, 2, 4))
    if min(native.values()) > mesh_x:
        verdict = ("LOCAL TIER BINDS AND READS WORSE -- the wide backbone "
                   "cannot rescue the concentrated local tier; the poured-"
                   "mesh reading was optimistic on structure")
    elif all_local and all(abs(v - mesh_x) < 1e-9 for v in native.values()):
        verdict = ("TIE WITH A MIGRATED BOTTLENECK -- the number matches "
                   "the poured reading by coincidence of this host's "
                   "funnels (grid 4 == gateway k=4), but the binding "
                   "resource is the LOCAL gateway port at every W: the "
                   "backbone's width cannot be consumed here (W = 1/2/4 "
                   "identical), so the poured-mesh reading was right "
                   "numerically and wrong structurally -- exactly what "
                   "the fidelity upgrade exists to reveal")
    else:
        verdict = ("BACKBONE RELIEF -- the native structure reads at or "
                   "below the poured-mesh baseline")
    out = {"anchor_gbps_per_channel": ANCHOR_GBPS,
           "rows": rows, "verdict": verdict,
           "caliber": ("ffn1 fixture flows, macro level (the anchor's "
                       "home); serialization vs the star floor; FlooNoC "
                       "bandwidth per physical channel (declared); tile "
                       "[2,2] declared example")}
    with open(os.path.join(OUT, "hier_wide.json"), "w") as f:
        json.dump(out, f, indent=1)

    labels = list(rows)
    xs = [rows[l]["x_vs_star"] for l in labels]
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    colors = ["#8fa8bf", "#555555", "#d1495b", "#e8a13c", "#2a9d8f"]
    ax.bar(range(len(labels)), xs, color=colors[:len(labels)])
    for i, (l, x) in enumerate(zip(labels, xs)):
        ax.text(i, x * 1.01, f"{x:.2f}x", ha="center", va="bottom",
                fontsize=8)
        ax.text(i, x * 0.5, rows[l]["bottleneck"].split("/")[-2]
                if "/" in rows[l]["bottleneck"] else "", ha="center",
                fontsize=6, rotation=90, color="white")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("serialization vs star floor")
    ax.set_title(f"The FlooNoC anchor on its own structural class\n"
                 f"(ffn1 flows at {ANCHOR_GBPS} GB/s per channel)",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "hier_wide_fidelity.png"), dpi=160)

    L = ["# hier_wide: the FlooNoC-class fidelity readout (C63-e; post-v6)",
         "", f"Anchor: {ANCHOR_GBPS} GB/s per physical channel (declared).",
         "",
         "| variant | serialization (x star) | bottleneck resource |",
         "|---|---|---|"]
    for l in labels:
        r = rows[l]
        L.append(f"| {l} | {r['x_vs_star']:.3f} | `{r['bottleneck']}` |")
    L += ["", f"**Verdict: {verdict}.**", "", out["caliber"], "",
          "![fidelity](hier_wide_fidelity.png)", ""]
    with open(os.path.join(OUT, "hier_wide.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    for l in labels:
        print(f"{l:20} {rows[l]['x_vs_star']:.3f}x  {rows[l]['bottleneck']}")
    print("verdict:", verdict)


if __name__ == "__main__":
    main()
