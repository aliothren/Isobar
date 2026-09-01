"""O29: the phase diagram -- the figure the paper is built around.

Two panels on the SAME (t_MVM x bandwidth) plane, all closed-form from
stored components (zero mapper): on-die per-link (left; prefill, attention
offloaded -- the S-independent condition) and die-to-die (right). The
right panel's semantics (C35): the black d = 1024 line is the PURE
hand-off stream (every operator fits its die; only the hidden state
crosses); the d >= 2560 lines are BLOCK CHAINS INCLUDING their spanning
operators (column split, tensor once: each receiving die takes the full
input, so these lines already contain the flood and sit ABOVE the purple
SINGLE 4-die OPERATOR line); the capacity ratio decides who spans -- it
selects among the lines, it is not an axis. Every narrative element has one visual
carrier: the mechanism = the slope (-1: boundary bandwidth ~ V / t_MVM);
the boundary FAMILY = one line per width tier (C33; d = 1024 is the
production base); the device axis = the horizontal coordinate; the
ecosystem mismatch = where things sit (analog chips as points with error
bars, digital NoC anchors as horizontal LINES, never points); the current
conclusion = the three shaded layers (below the point-to-point knee
everything contends; between it and the bus knee the organisation decides;
above, placement-free -- at the production scale, the family moves the
edges); the trend = the two arrows; the validation = independent points
coloured AND shaped by measured / closed-form (filled circle < 1.05, open
diamond 1.05-1.5, cross > 1.5 -- grayscale-safe): the 17c probes on the
left (the ffn2 tiler step shows as crosses, honestly off the line), the
measured B2 chain marks on the right; the collapse inset (g x t_MVM).

Pitfalls the caption states: (1) beyond ~d* the busiest wire is the input
trunk and the up traffic is the other half of the story below it; (2) the
analog-reality bands and the HERMES / ISAAC bandwidth coordinates are
ESTIMATES, and the surface between the silicon marks (four since C36) is
closed form,
not measurement; (3) the digital anchors are NoC links -- upper bounds,
never operating points of analog chips.

Inputs: analysis/phase_sweep.json (plane, d_family, b2_marks, collapse,
t1_hub), analysis/scaling_law_summary.json, the registry.
Outputs: analysis/phase_diagram.png + analysis/phase_diagram_table.md.

Usage (container): python3 scripts/analyze_phase_diagram.py
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts import anchors as an

OUT = "/home/workspace/analysis"
SWEEP = json.load(open(os.path.join(OUT, "phase_sweep.json")))
PLANE = SWEEP["plane"]
LAW = json.load(open(os.path.join(OUT, "scaling_law_summary.json")))
T_REF = PLANE["t_ref_s"]
REF_GBPS = SWEEP["fixed"]["ref_gbps"]
MAIN = PLANE["ondie"]["conditions"][PLANE["ondie"]["main_condition"]]
FAM = PLANE["d_family"]
T_LO, T_HI = 0.05, 100.0                       # us
TT = np.geomspace(T_LO, T_HI, 128)             # x grid, us

# marker code by measured / closed-form agreement (shape carries it in grayscale)
def agree_marker(r):
    if r < 1.05:
        return dict(marker="o", mfc="#2a7d4f", mec="#1b5233", ms=6)
    if r < 1.5:
        return dict(marker="D", mfc="none", mec="#c8791b", ms=6, mew=1.4)
    return dict(marker="x", mfc="none", mec="#b3282d", ms=7, mew=1.8)


STEP_MARKER = dict(marker="s", mfc="none", mec="#b3282d", ms=7, mew=1.5)   # known tiler step: expected off-line


def line(b_tref):
    return b_tref * (T_REF * 1e6) / TT


def draw_layers(ax, lo_tref, hi_tref, labels):
    """Three diagonal layers between the slope -1 boundaries at the
    production scale: contended / organisation decides / free."""
    y_lo, y_hi = line(lo_tref), line(hi_tref)
    ax.fill_between(TT, 1e-4, y_lo, color="0.86", lw=0, zorder=0)
    ax.fill_between(TT, y_lo, y_hi, color="0.93", lw=0, zorder=0)
    ax.fill_between(TT, y_hi, 1e5, color="1.0", lw=0, zorder=0)
    ax.plot(TT, y_lo, "-", color="0.45", lw=1.0, zorder=2)
    ax.plot(TT, y_hi, "-", color="0.45", lw=1.0, zorder=2)
    for frac, txt, col in labels:
        ax.text(0.985, frac, txt, transform=ax.transAxes, fontsize=6.6,
                ha="right", va="center", color=col, style="italic", zorder=6)


def draw_anchors(ax, level, band_label):
    for a in an.digital(level):
        ax.axhline(a.gbps, color="0.2", ls=(0, (1, 2)), lw=1.1, zorder=3)
        ax.text(T_LO * 1.06, a.gbps * 1.1, f"{a.label} [{a.status}]",
                fontsize=6.2, color="0.2", va="bottom", zorder=6,
                bbox=dict(fc="white", ec="none", alpha=0.75, pad=0.6))
    b = an.band(level)
    ax.axhspan(b.band[0], b.band[1], color="#c9a227", alpha=0.14, lw=0, zorder=1)
    ax.text(0.985, np.sqrt(b.band[0] * b.band[1]), band_label, fontsize=6.2,
            color="#7a5c00", va="center", ha="right",
            transform=ax.get_yaxis_transform(), zorder=6)


def fam_style(dk):
    return {"1024": dict(color="0.05", ls="-", lw=2.0),
            "2560": dict(color="#1d3557", ls=(0, (6, 2)), lw=1.6),
            "4096": dict(color="#33567e", ls=(0, (4, 2, 1, 2)), lw=1.6),
            "8192": dict(color="#5d7ea3", ls=(0, (1, 1.4)), lw=1.8)}[dk]


def device_marks(ax, y_frac=0.035):
    for c in an.device_marks():
        x = c.t_mvm_s * 1e6
        ax.axvline(x, color="0.55", ls=":", lw=0.8, zorder=2)
        ax.text(x, 0.005, f"{c.label.split(' (')[0]} [{c.t_mvm_status}]",
                rotation=90, fontsize=6.0, ha="right", va="bottom",
                transform=ax.get_xaxis_transform(), color="0.4", zorder=6)


def main():
    fig, axes = plt.subplots(1, 2, figsize=(13.6, 6.0))

    # ================= left: on-die per-link =================
    ax = axes[0]
    star = MAIN["star (private links)"]["boundary_gbps_at_tref"]
    bus = MAIN["bus (shared medium)"]["boundary_gbps_at_tref"]
    draw_layers(ax, star, bus,
                [(0.22, "everything contends\n(below the point-to-point knee)", "0.30"),
                 (0.50, "the organisation decides\n(scheme choice: star ... bus)", "0.35"),
                 (0.88, "", "0.45")])
    ax.text(0.315, 0.93, "placement-free", transform=ax.transAxes, fontsize=6.6,
            ha="center", va="center", color="0.45", style="italic", zorder=6)
    draw_anchors(ax, an.ONDIE, "analog-reality tier [estimated]")
    for dk in ("1024", "2560", "4096", "8192"):
        b = FAM["ondie"][dk]["boundary_gbps_at_tref"]
        lab = FAM["labels"][dk]
        ax.plot(TT, line(b), zorder=4,
                label=f"routed boundary, d={dk}: {lab}", **fam_style(dk))
    # chips: a published bandwidth is a POINT, an estimated one an error bar;
    # NeuRRAM has no on-die number (hub-IO)
    for c in an.device_marks():
        if c.key == "neurram":
            continue
        x = c.t_mvm_s * 1e6
        short = c.label.split(" (")[0].replace("Mythic AMP M1076", "Mythic M1076")
        if c.ondie_gbps is not None:                 # HERMES, normalized to our granularity (C37)
            ax.plot([x], [c.ondie_gbps], marker="s", color="0.1", mfc="0.1", ms=6, zorder=5)
            ax.text(x * 1.22, c.ondie_gbps * 0.72,
                    f"{short}\n[supply ~{c.ondie_gbps:.0f} GB/s per 32-array group\n"
                    f"(0.4 GB/s/physical link published; C37);\n"
                    f"provisioned ~1.36x above its own knee]",
                    fontsize=5.8, va="top", color="0.1", zorder=6,
                    bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.6))
        else:
            lo, hi = c.ondie_band
            mid = np.sqrt(lo * hi)
            ax.errorbar([x], [mid], yerr=[[mid - lo], [hi - mid]], fmt="s",
                        color="0.1", mfc="white", ms=5, capsize=3, lw=1.1, zorder=5)
            ax.text(x * 1.22, lo * 1.15, f"{short}\n[b/w {c.ondie_status.split(' (')[0]}]",
                    fontsize=6.0, va="bottom", color="0.1", zorder=6,
                    bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.6))
    nr = an.chip("neurram")
    ax.plot([nr.t_mvm_s * 1e6], [1.5e-3], marker="^", color="0.1", ms=7, zorder=6)
    ax.text(nr.t_mvm_s * 1e6 * 1.1, 1.5e-3, "NeuRRAM [t measured;\non-die b/w not published: hub-IO]",
            fontsize=5.8, va="center", color="0.1", zorder=6)
    # validation points: the 17c probes, re-scored routed knee vs the trunk law
    for name in ("qkv_proj", "ffn1", "ffn2"):
        for dstr, row in LAW["scheme_check"][name].items():
            d = int(dstr)
            if d < 2560:
                continue                              # below d*: the mapper-shaped regime
            meas = REF_GBPS * row["mesh, glb centre"]
            pred = REF_GBPS * 4.0 * d / LAW["trunk_denominator"]
            r = max(meas / pred, pred / meas)
            st = STEP_MARKER if (name == "ffn2" and r > 1.5) else agree_marker(r)
            ax.plot([T_REF * 1e6], [meas], ls="none", zorder=6, **st)
    ax.annotate("known tiler step (ffn2): x2 off the\nline at d <= 4096 -- measured and\nexpected (the macro C split; C32)",
                (T_REF * 1e6, REF_GBPS * 4 * 2 * 2560 / LAW["trunk_denominator"]),
                textcoords="offset points", xytext=(18, 42), fontsize=6.2,
                color="#b3282d", zorder=6, ha="left",
                bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.6),
                arrowprops=dict(arrowstyle="-", color="#b3282d", lw=0.7))
    # trend arrows
    x_ar = 0.105
    i_ar = int(np.searchsorted(TT, x_ar))
    ax.annotate("", xy=(x_ar, line(FAM["ondie"]["8192"]["boundary_gbps_at_tref"])[i_ar] * 1.3),
                xytext=(x_ar, line(FAM["ondie"]["1024"]["boundary_gbps_at_tref"])[i_ar] * 0.75),
                arrowprops=dict(arrowstyle="-|>", color="0.15", lw=1.3), zorder=6)
    ax.text(x_ar * 1.15, 190, "model scale\nmoves the boundary", fontsize=6.4, color="0.15", zorder=6)
    ax.annotate("", xy=(0.28, 3.2e-3), xytext=(4.2, 3.2e-3),
                arrowprops=dict(arrowstyle="-|>", color="0.15", lw=1.3), zorder=6)
    ax.text(1.1, 4.4e-3, "faster devices move the chips", fontsize=6.6,
            color="0.15", ha="center", zorder=6)
    # collapse inset
    ins = ax.inset_axes([0.60, 0.075, 0.225, 0.225])
    coll = PLANE["collapse"]
    gt = [x * 1e9 for x in coll["gt_grid_gb"]]
    for m, mk in zip(PLANE["marks"], ("o", "v", "s", "D")):
        pm = coll["per_mark"][m["key"]]
        ins.plot(gt, pm["matrix_mult"], ls="-", marker=mk, ms=2.0, lw=0.7,
                 color="0.2", markevery=6)
    ins.set_xscale("log"); ins.set_yscale("log")
    ins.set_title("collapse: the 4 silicon marks, one curve\nx = b/w x t_MVM (bytes/row-time, log)", fontsize=5.6)
    ins.tick_params(labelsize=5, labelbottom=False)
    ins.grid(alpha=0.25, which="both")
    ax.set_title("on-die, per link (T2) -- prefill, attention offloaded (S-independent)\n"
                 "boundary: busiest operator's traffic = its compute; slope -1 = the mechanism",
                 fontsize=9)
    ax.legend(fontsize=6.4, loc="upper right", framealpha=0.95)

    # ================= right: die-to-die =================
    ax = axes[1]
    handoff = FAM["d2d"]["1024"]["boundary_gbps_at_tref"]
    probe = SWEEP["plane"]["d2d"]["cases"]["B3 probe | clustered"]["boundary_gbps_at_tref"]
    draw_layers(ax, handoff, probe,
                [(0.10, "even the pure hand-off stream contends", "0.30"),
                 (0.30, "hand-off fine; any die-spanning operator exposed\n(the capacity ratio decides who spans)", "0.35"),
                 (0.62, "the single spanning operator fine too;\nthe block-chain family (drawn) sets what remains", "0.45")])
    draw_anchors(ax, an.D2D, "analog-reality tier [estimated]")
    for dk in ("1024", "2560", "4096", "8192"):
        b = FAM["d2d"][dk]["boundary_gbps_at_tref"]
        if dk == "1024":
            lab = ("PURE hand-off stream, d=1024: 355M production (ops fit their die;\n"
                   "only the hidden state crosses; = die<->unit link under offload, both phases)")
        else:
            model = FAM["labels"][dk].split(": ")[-1] if ": " in FAM["labels"][dk] else FAM["labels"][dk]
            lab = f"block chain INCL. spanning operators (column split, tensor once), d={dk}: {model}"
        ax.plot(TT, line(b), zorder=4, label=lab, **fam_style(dk))
    ax.plot(TT, line(probe), ls=(0, (7, 2, 1.5, 2)), color="#7b2d8b", lw=2.0, zorder=4,
            label="SINGLE 4-die operator (probe, measured): one spanning op alone")
    device_marks(ax)
    # validation: the measured B2 chain marks sit on the d=2560 line
    b2 = PLANE["b2_marks"]["clustered"]
    pred = FAM["d2d"]["2560"]["boundary_gbps_at_tref"]
    for mkey, mv in b2["marks"].items():
        r = max(mv["boundary_gbps"] / (pred * T_REF / mv["t_mvm_s"]),
                (pred * T_REF / mv["t_mvm_s"]) / mv["boundary_gbps"])
        ax.plot([mv["t_mvm_s"] * 1e6], [mv["boundary_gbps"]], ls="none",
                zorder=6, **agree_marker(r))
    ax.text(0.02, 0.03, "validation: the measured 2.7B block chain\n(4 silicon speeds) sits on the\nclosed-form d=2560 line",
            transform=ax.transAxes, fontsize=6.2, color="#1b5233", va="bottom", zorder=6)
    ax.set_title("die-to-die (T2) -- pure hand-off (black) / block chains INCL. spanning ops (blue family)\n"
                 "/ a single spanning operator (purple); the d>=2560 chains carry the flood, hence above the probe",
                 fontsize=8.6)
    ax.legend(fontsize=6.2, loc="upper right", framealpha=0.95)

    for ax, ylim in zip(axes, ((1e-3, 1e4), (5e-4, 1e3))):
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlim(T_LO, T_HI); ax.set_ylim(*ylim)
        ax.set_xlabel("device speed: t_MVM per input row (us)  [<- faster silicon]")
        ax.set_ylabel("link bandwidth, per direction (GB/s)")
    lg = [plt.Line2D([], [], ls="none", **agree_marker(1.0)),
          plt.Line2D([], [], ls="none", **agree_marker(1.2)),
          plt.Line2D([], [], ls="none", **agree_marker(2.0)),
          plt.Line2D([], [], ls="none", **STEP_MARKER)]
    fig.legend(lg, ["measured / closed form < 1.05 (on the line)", "1.05 - 1.5", "> 1.5 (unexplained)",
                    "known tiler step (ffn2; expected off-line)"],
               loc="lower center", ncol=4, fontsize=6.4, frameon=False,
               bbox_to_anchor=(0.5, -0.005))
    fig.suptitle("The phase diagram (O29): when does communication become first-order on analog CIM?\n"
                 "boundaries closed-form from measured traffic; anchors = digital NoC links (upper bounds, "
                 "never analog operating points); bands and chip bandwidths estimated", fontsize=9.5)
    fig.subplots_adjust(left=0.055, right=0.985, top=0.865, bottom=0.115, wspace=0.16)
    p = os.path.join(OUT, "phase_diagram.png")
    fig.savefig(p, dpi=140)
    fig.savefig(p.replace(".png", "_gray.png"), dpi=110)   # grayscale check copy
    import PIL.Image
    PIL.Image.open(p.replace(".png", "_gray.png")).convert("L").save(p.replace(".png", "_gray.png"))
    plt.close(fig)
    print(f"PNG -> {p} (+ _gray.png grayscale check)")

    # ---- the grid -> ratio table
    handoff_b = FAM["d2d"]["1024"]["boundary_gbps_at_tref"]
    probe_b = SWEEP["plane"]["d2d"]["cases"]["B3 probe | clustered"]["boundary_gbps_at_tref"]
    rows = []
    rows.append("# The phase diagram's grid -> ratio table (generated by analyze_phase_diagram.py)\n")
    rows.append("\nBoundary positions in GB/s at the silicon marks (r = 1: busiest "
                "operator's traffic = compute; above the value the network is hidden).\n")
    marks = an.device_marks()
    hdr = "| level / boundary | " + " | ".join(
        f"{c.label.split(' (')[0].replace('Mythic AMP M1076', 'Mythic M1076').replace(' 64-core', '')} "
        f"{c.t_mvm_s*1e6:.3g} us" for c in marks) + " |"
    rows += [hdr, "|---|" + "---|" * len(marks)]
    def row(name, b):
        cells = " | ".join(f"{b * T_REF / c.t_mvm_s:.3g}" for c in marks)
        rows.append(f"| {name} | {cells} |")
    row("on-die, star (production d=1024)", star)
    for dk in ("1024", "2560", "4096", "8192"):
        row(f"on-die, routed, d={dk} ({FAM['labels'][dk]})", FAM["ondie"][dk]["boundary_gbps_at_tref"])
    row("on-die, bus (production d=1024)", bus)
    row("T1 die-buffer hub (production; = bus + in-fill; MX100-class axis)",
        SWEEP["t1_hub"]["conditions"]["prefill, attention offloaded"]["thresholds_gbps"]["busiest_op_net_eq_comp"])
    row("D2D pure hand-off stream, d=1024 (production)", handoff_b)
    for dk in ("2560", "4096", "8192"):
        row(f"D2D block chain incl. spanning ops, d={dk}", FAM["d2d"][dk]["boundary_gbps_at_tref"])
    row("D2D single 4-die operator (probe)", probe_b)
    rows.append("\nReadout at the bandwidth columns (production base, knee ffn2, routed; "
                "r = boundary / column bandwidth -- r > 1 means the network is exposed):\n")
    rows += ["| device | " + " | ".join(f"{lab} [{st}]" for _, lab, _, _, st in an.columns(an.ONDIE)) + " |",
             "|---|" + "---|" * len(an.columns(an.ONDIE))]
    for c in marks:
        b = FAM["ondie"]["1024"]["boundary_gbps_at_tref"] * T_REF / c.t_mvm_s
        cells = " | ".join(f"{b / gb:.2f}" for _, _, gb, _, _ in an.columns(an.ONDIE))
        rows.append(f"| {c.label} | {cells} |")
    tp = os.path.join(OUT, "phase_diagram_table.md")
    with open(tp, "w") as f:
        f.write("\n".join(rows) + "\n")
    print(f"table -> {tp}")
    print("\n".join(rows[3:12]))


if __name__ == "__main__":
    main()
