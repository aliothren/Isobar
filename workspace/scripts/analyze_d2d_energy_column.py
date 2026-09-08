"""The die-level D2D ENERGY column (O27 pre-flight check, post-v6).

Pre-registered in FIXLIST step 8: the on-die "energy is flat" result must
not vouch for the die tier -- die-level soft placement changes charged
D2D transport (average hops under the C23 convention), and the D2D unit
price is 1-2 orders above on-die. This script adds the never-surfaced
energy column to the EXISTING die-level sweeps, zero mapper.

CONVENTION (the correction to the review's naive bytes x price): the
repo charges flat (words x pJ at the reference hop, inside the CiMLoop
account) + the surplus overlay (words x pJ x (hops - 1)); the TOTAL
scales with average hops. GATE: the stored surplus values must be
REPRODUCED from words x (hops-1) x pJ before anything is added.

Scenarios: B1 = the stored 48-die ordering sweep (d2d_impact.json);
B3 = the stored 4-die probe placements (multidie_placement.json);
B2 = the 2.7B chain's three seating styles, closed form (block_chain +
seat_block + block_die_flows -- the same machinery as the published
latency numbers). Outputs: three numbers per scenario + the figure.

    python3 scripts/analyze_d2d_energy_column.py
      -> analysis/d2d_energy_column.json + analysis/d2d_energy_column.png
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts import llm_workload as lw
from scripts import fabric as fabric_mod
from scripts import placement as pm

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
A = os.path.join(WS, "analysis")
PJ = 10.0                                   # GRS band midpoint (per word)
MULTI24 = os.path.join(WS, "models", "fabric", "mlx300_multidie.yaml")


def b1_orderings():
    d = json.load(open(os.path.join(A, "d2d_impact.json")))
    S, n_dies = d["S"], d["n_dies"]
    cfg = lw.GptConfig()
    words_boundary = S * cfg.d_model                    # hidden state, prefill
    n_bound = n_dies - 1
    W = words_boundary * n_bound                        # 24,641,536
    rows = []
    for a in d["assignments"]:
        surplus_calc = W * (a["avg_hops"] - 1.0) * PJ * 1e-12
        stored = a["surplus_uJ"] * 1e-6
        gate = (abs(surplus_calc - stored) <= 1e-6 * max(stored, 1e-12)
                or (stored == 0.0 and surplus_calc == 0.0))
        assert gate, (a["assignment"], surplus_calc, stored)
        total = W * a["avg_hops"] * PJ * 1e-12          # flat + surplus
        rows.append({"assignment": a["assignment"], "avg_hops": a["avg_hops"],
                     "latency_multiplier": a["busiest_x"],
                     "d2d_energy_J": total})
    base = min(r["d2d_energy_J"] for r in rows)
    for r in rows:
        r["energy_norm"] = r["d2d_energy_J"] / base
    # decode transfer (declared): same hops, words/boundary = d_model
    dec_scale = cfg.d_model / words_boundary
    sys_p = json.load(open(os.path.join(A, "gpt2_system_totals_prefill.json")))["scenarios"]
    sys_d = json.load(open(os.path.join(A, "gpt2_system_totals_decode.json")))["scenarios"]
    shares = {}
    worst = max(rows, key=lambda r: r["d2d_energy_J"])
    best = min(rows, key=lambda r: r["d2d_energy_J"])
    for tag, den in (("prefill_onchip", sys_p["A_E"]),
                     ("prefill_offloaded", sys_p["B_E"])):
        shares[tag] = {"best": best["d2d_energy_J"] / den,
                       "worst": worst["d2d_energy_J"] / den}
    for tag, den in (("decode_onchip", sys_d["A_E"]),
                     ("decode_offloaded", sys_d["B_E"])):
        shares[tag] = {"best": best["d2d_energy_J"] * dec_scale / den,
                       "worst": worst["d2d_energy_J"] * dec_scale / den}
    return {"rows": rows, "shares": shares,
            "ratio_worst_best": worst["d2d_energy_J"] / best["d2d_energy_J"],
            "gate": "stored surplus reproduced exactly",
            "tie_break": {"pair": ("snake", "sequential rows"),
                          "latency": "tied at 1.0x",
                          "energy": rows[1]["energy_norm"]}}


def b3_probe():
    d = json.load(open(os.path.join(A, "multidie_placement.json")))
    # infer the charged word total from the stored surplus (gate: one W
    # must fit every placement)
    Ws = [p["surplus_J"] / ((p["mean_hops"] - 1.0) * PJ * 1e-12)
          for p in d["placements"] if p["mean_hops"] > 1.0 + 1e-9]
    W = Ws[0]
    assert all(abs(w - W) < 1e-6 * W for w in Ws), Ws
    rows = []
    for p in d["placements"]:
        # uniform boundary flows (single op, equal edges) => E = W x mean x pJ
        # exactly; co-located flows (dist 0) charge nothing. Latency read at
        # the stored low-bandwidth column (256 w/c), where placement binds.
        lat = p["lat_s"]["256"] if isinstance(p["lat_s"], dict) else p["lat_s"]
        total = W * p["mean_hops"] * PJ * 1e-12
        rows.append({"label": p["label"], "mean_hops": p["mean_hops"],
                     "lat_s": lat, "d2d_energy_J": total})
    base = min(r["d2d_energy_J"] for r in rows)
    lbase = min(r["lat_s"] for r in rows)
    for r in rows:
        r["energy_norm"] = r["d2d_energy_J"] / base
        r["lat_norm"] = r["lat_s"] / lbase
    order_l = sorted(rows, key=lambda r: r["lat_s"])
    order_e = sorted(rows, key=lambda r: r["d2d_energy_J"])
    return {"rows": rows, "charged_words": W,
            "ratio_worst_best": max(r["d2d_energy_J"] for r in rows) / base,
            "same_direction": [r["label"] for r in order_l]
                              == [r["label"] for r in order_e],
            "share": "n/a (single-op probe; no system denominator -- declared)"}


def b2_chain():
    fab = fabric_mod.from_yaml(MULTI24)
    full = json.load(open(os.path.join(A, "scale_2p7b_per_op.json")))
    c = full["config"]
    cfg = lw.GptConfig(d_model=c["d_model"], n_heads=c["n_heads"],
                       d_ff=c["d_ff"], n_layers=c["n_layers"], name=c["name"])
    S = c.get("S", 512)
    out = {}
    from scripts import interconnect as ic_mod
    pl = pm.sequential_fill(fab)
    ic = ic_mod.build(fab, "die", pl)
    for cond, phase, on_chip in (("prefill_onchip", "prefill", True),
                                 ("decode_offloaded", "decode", False)):
        chain = lw.block_chain(cfg, S, phase, on_chip=on_chip)
        rows = []
        for style in ("clustered", "row-fill", "spread"):
            seating = lw.seat_block(fab, chain, style)
            flows = lw.block_die_flows(chain, seating, fab)
            # block_die_flows leaves distance = 0.0 (filled downstream);
            # charge actual per-flow hops from the seating, width included
            e = lat_vol = 0.0
            for fl in flows.values():
                for f in fl:
                    a, b = f["nodes"]
                    if ic_mod.HUB in (a, b):
                        h = 1.0            # the unit attach hand-off (flat)
                    else:
                        h = ic.energy_hops(a, b)
                    e += f["volume"] * f.get("width", 1.0) * PJ * 1e-12 * h
                    lat_vol = max(lat_vol, f["volume"] * f.get("width", 1.0) * h)
            rows.append({"style": style, "d2d_energy_J": e,
                         "busiest_volxdist": lat_vol})
        base = min(r["d2d_energy_J"] for r in rows)
        for r in rows:
            r["energy_norm"] = r["d2d_energy_J"] / base
        order_e = sorted(rows, key=lambda r: r["d2d_energy_J"])
        order_l = sorted(rows, key=lambda r: r["busiest_volxdist"])
        lat_best = min(rows, key=lambda r: r["busiest_volxdist"])
        out[cond] = {"rows": rows,
                     "ratio_worst_best": max(r["d2d_energy_J"] for r in rows) / base,
                     "same_direction": [r["style"] for r in order_l]
                                       == [r["style"] for r in order_e],
                     "latency_best_style": lat_best["style"],
                     "cost_of_latency_best": lat_best["d2d_energy_J"] / base - 1.0}
    return out


def main():
    res = {"convention": "total = words x pJ x avg_hops (flat + surplus; "
                         "C23 replace-never-add)",
           "B1_orderings_48die": b1_orderings(),
           "B3_probe_4die": b3_probe(),
           "B2_chain_2p7b": b2_chain()}
    with open(os.path.join(A, "d2d_energy_column.json"), "w") as f:
        json.dump(res, f, indent=1)

    b1, b3, b2 = res["B1_orderings_48die"], res["B3_probe_4die"], res["B2_chain_2p7b"]
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.2))
    LAT_C, EN_C, EN_LIGHT = "#4477AA", "#EE7733", "#F6C6A0"   # latency / energy

    ax = axes[0]
    labs = [r["assignment"].replace(" (adversarial)", "\n(adversarial)")
            for r in b1["rows"]]
    x = np.arange(len(labs))
    ax.bar(x - 0.19, [r["latency_multiplier"] for r in b1["rows"]], 0.34,
           color=LAT_C, label="latency multiplier (max-functional)")
    ax.bar(x + 0.19, [r["energy_norm"] for r in b1["rows"]], 0.34,
           color=EN_C, label="D2D energy, normalized (sum-functional)")
    ax.set_xticks(x); ax.set_xticklabels(labs, fontsize=7)
    ax.set_title("B1  48-die orderings: the energy column surfaces\n"
                 "a latency TIE broken by 1.74x energy", fontsize=8.5)
    ax.annotate("latency-tied,\n1.74x apart in energy",
                xy=(1.19, b1["rows"][1]["energy_norm"]), xytext=(0.55, 4.4),
                fontsize=7, color="0.2",
                arrowprops=dict(arrowstyle="->", color="0.4", lw=0.9))
    ax.text(0.02, 0.55, "adversarial = CONSTRUCTED\nstress position (a probe of\n"
            "the form, not a natural\ncandidate); real-space\nspread = 1.74x",
            transform=ax.transAxes, fontsize=6.4, ha="left", va="top",
            color="0.25")
    ax.legend(fontsize=6.6)
    ax.set_ylabel("x (each normalized to its own best)", fontsize=8)

    ax = axes[1]
    series = []
    for rows, marker, color, name in ((b3["rows"], "o", LAT_C, "4-die probe seatings"),
                                      (b2["prefill_onchip"]["rows"], "D", EN_C,
                                       "2.7B chain styles (prefill)")):
        xs = [r.get("lat_norm", r.get("busiest_volxdist", 0) /
                    min(q.get("busiest_volxdist", 1) for q in rows))
              for r in rows]
        ys = [r["energy_norm"] for r in rows]
        ax.plot(xs, ys, ls="none", marker=marker, ms=6, mfc="white",
                color=color, label=name)
        series.append((rows, xs, ys, marker, color))
    m = 5.8
    ax.plot([1, m], [1, m], color="0.7", lw=0.8, ls=":", zorder=0,
            label="lat = energy (co-directional)")
    for rows, xs, ys, marker, color in series:
        for r, xx, yy in zip(rows, xs, ys):
            if yy > 1.3 or xx > 1.5:                      # far points: label in place
                lab = r.get("label", r.get("style", ""))
                far_offs = {"top row (default)": (9, -5)}
                ax.annotate(f"{lab}\n(lat {xx:.2f}, E {yy:.2f})", (xx, yy),
                            textcoords="offset points",
                            xytext=far_offs.get(lab, (6, 2)),
                            fontsize=6, color="0.15")
    ax.annotate("inversion: corners beats\none-column on latency,\ncosts more D2D energy",
                xy=(2.05, 5.28), xytext=(1.15, 4.35), fontsize=6.4, color="0.2",
                arrowprops=dict(arrowstyle="->", color="0.4", lw=0.9))
    # zoom inset: the near-optimum cluster with the numbers ON the figure
    ins = ax.inset_axes([0.52, 0.07, 0.45, 0.40])
    for rows, xs, ys, marker, color in series:
        for r, xx, yy in zip(rows, xs, ys):
            if yy <= 1.3 and xx <= 1.5:
                ins.plot([xx], [yy], ls="none", marker=marker, ms=6,
                         mfc="white", color=color)
                lab = r.get("label", r.get("style", ""))
                offs = {"clustered at anchor": (4, -9), "clustered": (4, 5),
                        "row-fill": (2, 6), "spread": (2, -10)}
                ins.annotate(f"{lab} (lat {xx:.2f}, E {yy:.2f})", (xx, yy),
                             textcoords="offset points",
                             xytext=offs.get(lab, (4, 3)), fontsize=5.8)
    ins.plot([0.97, 1.45], [0.97, 1.45], color="0.7", lw=0.7, ls=":")
    ins.set_xlim(0.97, 1.45); ins.set_ylim(0.96, 1.14)
    ins.tick_params(labelsize=5.5)
    ins.set_title("near-optimum, zoomed", fontsize=6.2)
    ax.indicate_inset_zoom(ins, edgecolor="0.6")
    ax.set_xlabel("latency metric, normalized to best", fontsize=8)
    ax.set_ylabel("D2D energy, normalized to best", fontsize=8)
    ax.set_title("B2 + B3  seatings: orderings diverge off-optimum\n"
                 "(max- vs sum-functional); latency-best stays energy-best\n"
                 "(B3: E 1.00) or within 8.3% (B2 clustered, E 1.08)", fontsize=8.5)
    ax.legend(fontsize=6.6, loc="center left")

    ax = axes[2]
    tags = list(b1["shares"])
    x = np.arange(len(tags))
    ax.bar(x - 0.19, [b1["shares"][t]["best"] * 100 for t in tags], 0.34,
           color=EN_LIGHT, edgecolor=EN_C, linewidth=0.8, label="best ordering")
    ax.bar(x + 0.19, [b1["shares"][t]["worst"] * 100 for t in tags], 0.34,
           color=EN_C, label="worst ordering")
    ax.axhline(1.0, color="0.5", lw=0.9, ls="--")
    ax.text(0.02, 1.05, "1% line", fontsize=6.5, color="0.4")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels([t.replace("_", "\n") for t in tags], fontsize=7)
    ax.set_ylabel("D2D energy share of scenario energy (%)", fontsize=8)
    ax.set_title("B1  the share: SUB-percent everywhere -- so the\n"
                 "divergences never touch system energy (<0.1% worst)",
                 fontsize=8.5)
    ax.legend(fontsize=6.6)

    for ax in axes:
        ax.tick_params(labelsize=7)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.suptitle("The die-level D2D energy column (O27 pre-flight, post-v6):\n"
                 "the ordering lever is real (6.55x incl. the constructed stress; 1.74x in real space), the share is "
                 "SUB-PERCENT BOUNDED, orderings diverge off-optimum -- energy = a decisive tie-breaker",
                 fontsize=9.2)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(os.path.join(A, "d2d_energy_column.png"), dpi=170)

    print("B1 ratio", round(b1["ratio_worst_best"], 3),
          "tie-break energy", round(b1["rows"][1]["energy_norm"], 3))
    for t, s in b1["shares"].items():
        print(f"  share {t}: best {s['best']:.4%} worst {s['worst']:.4%}")
    print("B3 ratio", round(b3["ratio_worst_best"], 3),
          "same-direction", b3["same_direction"])
    for cond, d in b2.items():
        print(f"B2 {cond}: ratio {d['ratio_worst_best']:.3f} "
              f"same-direction {d['same_direction']} "
              f"styles {[ (r['style'], round(r['energy_norm'],3)) for r in d['rows'] ]}")


if __name__ == "__main__":
    main()
