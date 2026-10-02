"""The phase diagram, redrawn to the Isobar Fig.1 specification.

Writes analysis/phase_diagram_isobar.png -- a NEW file; the standing
analysis/phase_diagram.png is left untouched.

Per the spec: both axes are RATES (x = MVM row-processing rate
s = 1/t_row in Mrows/s, the reciprocal of the old axis, so every
boundary and chip is recomputed rather than swapped; y = link
bandwidth per direction). Three regions by the PLACEMENT EXTREMA of
the communication cost:

    max_P H < R              compute / fixed-cost dominated
    min_P H <= R <= max_P H  placement-dependent dominance
    min_P H > R              communication dominated

The lower region is NOT called placement-free: placement still decides
how severe the communication cost is there. With H = A(p)/B and
R(s) = N*s_ref/s + F the boundaries are B_-(s) = A_min/R(s) and
B_+(s) = A_max/R(s), which rise with s and FLATTEN wherever the
non-scaling terms (K/V write, digital unit) own R.

Spread contours (the spec's optional layer): for the same placement
set, S(s,B) = (A_max - A_min) / (B*R(s) + A_min) is the slowest
placement's latency excess over the fastest -- the DENOMINATOR IS
T_min OVER P, not the baseline and not the search's gain.

Port declaration (the spec requires it stated): each die has one
injection and one ejection port AT THE LINK RATE, so ports scale with
B together with the links, and H = A(p)/B holds with A taken over
links AND ports.

    python3 scripts/fig_phase_isobar.py
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts import anchors as an
from scripts import search_eval as se

KAPPA = float(os.environ.get("ISOBAR_KAPPA", "1"))   # S9: the package panel's port ratio
# Final form (2026-09-21): the two evaluated bandwidths as horizontal
# reference tiers across device speeds, the two NeuRRAM points joined
# vertically, the M1076 as ONE I/O-matched projected point instead of the
# assumed 0.4-8 GB/s range, marker semantics in the legend. ISOBAR_REFS=old
# reproduces the previous form into *_old files (comparison only).
REFS = os.environ.get("ISOBAR_REFS", "lines") == "lines"
REF_LINE, REF_TXT = "#8d84a3", "#6f6684"     # muted purple-grey for the reference tiers
_SFX = ("" if KAPPA == 1.0 else f"_k{KAPPA:g}") + ("" if REFS else "_old")
OUT_PNG = os.path.join(se.A, f"phase_diagram_isobar{_SFX}.png")
OUT_PDF = os.path.join(se.A, f"phase_diagram_isobar{_SFX}.pdf")
matplotlib.rcParams["pdf.fonttype"] = 42   # embed TrueType: text stays text in the PDF
OUT_JSON = os.path.join(se.A, f"phase_diagram_isobar{_SFX}.json")
S_LO, S_HI = 0.02, 40.0                     # Mrows/s
SS = np.geomspace(S_LO, S_HI, 256)
S_REF = 1.0 / 10.14e-6 / 1e6                # NeuRRAM's rate, Mrows/s

# palette: blue-grey regions of two depths with the amber band between
# them; both boundaries thin and grey so the envelope bar (charcoal,
# heavier) stands apart from them; no red anywhere.
SLATE, SLATE_TXT = "#6b7b8c", "#2b4a6f"          # boundaries grey; compute text navy
BRICK, BRICK_TXT = "#6b7b8c", "#1f2f3f"          # communication text: deep ink-blue
FILL_TOP, FILL_MID, FILL_BOT = "#f2f5f9", "#f1e5bd", "#d3dbe4"
BAND_TXT = "#7a5c00"
CHIP, CHIP_TXT = "#2a7d4f", "#1b5233"
CHARCOAL = "#222222"
CONTOUR = "#8c8c8c"
SPREADS = (0.20,)


def boundaries(a_min, a_max, n_scaling_s, fixed_s):
    """B_-(s), B_+(s) in GB/s. R(s) = N*s_ref/s + F with N the compute
    measured at the reference row rate."""
    r = n_scaling_s * (S_REF / SS) + fixed_s
    return a_min / r / 1e9, a_max / r / 1e9


def spread_contour(level, a_min, a_max, n_scaling_s, fixed_s):
    """B at which the placement set's latency spread equals `level`:
    S = (A_max - A_min)/(B*R + A_min)  =>  B = ((A_max-A_min)/S - A_min)/R."""
    r = n_scaling_s * (S_REF / SS) + fixed_s
    return ((a_max - a_min) / level - a_min) / r / 1e9


_INTRA = {}


def intra_die_model():
    """The intra-die panel's own cost model, read from the A3 enumeration
    (ffn die, 70 joint seatings): per op t = write + prop + max(compute,
    serialization(beta)/B). The masking switch is PER OP against ITS OWN
    compute (5.19 ms for both ffn ops at the NeuRRAM rate) -- not against
    the die's summed compute, which an earlier version of this panel used
    (F-FIG1a). Returns the per-seating per-op serialization words, the
    per-op compute at the reference rate, and the fixed (write + prop)
    part; A(beta) = max over ops of the serialization words."""
    if _INTRA:
        return _INTRA
    from scripts import analyze_soft_lever as asl
    from scripts import search_withindie as sw
    J = sw.WithinDieJ("ffn", "prefill", sw.G_ACTIVE)
    w2 = asl.REF_WC / an.CYCLE_S
    seatings = []
    for _c, _m, seat in J.exhaustive():
        seatings.append({n: J.a3_ser(n, seat[n]) * w2 for n, _ in J.ops})
    comp = {n: J.recs[n]["compute_s"] for n, _ in J.ops}
    fixed = sum(J.recs[n]["write_s"] + (J.recs[n]["latency_s"] - J.recs[n]["write_s"]
                - max(J.recs[n]["compute_s"], J.recs[n]["serial_s"])) for n, _ in J.ops)
    _INTRA.update({"seatings": seatings, "compute_ref_s": comp, "fixed_s": fixed,
                   "A": [max(s.values()) for s in seatings]})
    return _INTRA


def intra_die_curves(level=0.20):
    """(B_-, B_+, B at spread = level) on the SS grid under the max model.
    Boundaries: every op masked iff max_op ser/B <= c(s), c(s) = c_ref *
    s_ref / s (the ops share one compute), so B_c(beta) = A(beta) / c(s).
    The spread (T_max - T_min)/T_min over the 70 seatings is monotone in
    B and solved by bisection per s."""
    m = intra_die_model()
    c_ref = max(m["compute_ref_s"].values())
    a_min, a_max = min(m["A"]), max(m["A"])
    c = c_ref * (S_REF / SS)
    lo, hi = a_min / c / 1e9, a_max / c / 1e9
    fixed = m["fixed_s"]

    def spread(cs, B):
        Ts = [fixed + sum(max(cs, v / B) for v in s.values()) for s in m["seatings"]]
        return max(Ts) / min(Ts) - 1.0

    bc = np.empty_like(SS)
    for i, cs in enumerate(c):
        b_lo, b_hi = lo[i] * 1e9 * 1e-3, hi[i] * 1e9 * 1.5      # bracket in words/s
        if spread(cs, b_hi) > level:                             # cannot happen: 0 at B+
            bc[i] = b_hi / 1e9
            continue
        for _ in range(60):
            mid = math.sqrt(b_lo * b_hi)
            if spread(cs, mid) > level:
                b_lo = mid
            else:
                b_hi = mid
        bc[i] = math.sqrt(b_lo * b_hi) / 1e9
    return lo, hi, bc


def _angle_along(ax, x0, y0, x1, y1):
    """Screen angle of the segment (x0,y0)-(x1,y1) in data coords."""
    p0 = ax.transData.transform((x0, y0))
    p1 = ax.transData.transform((x1, y1))
    return float(np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0])))


# region wording per execution model: the package panel is a serial SUM,
# so a region says which cost DOMINATES; the intra-die panel is a per-op
# MAX, so a region says whether communication is EXPOSED or MASKED
LABELS_SUM = ("compute / fixed-cost\ndominated",
              "placement decides which dominates",
              "communication dominated\n(placement sets how severe)")
LABELS_MAX = ("communication masked",
              "placement decides what is exposed",
              "communication exposed\n(placement sets how severe)")


def draw_panel(ax, a_min, a_max, n_s, f_s, ylim, quantifier, p_desc,
               zones, env_x, curves=None, labels=LABELS_SUM):
    lo, hi = boundaries(a_min, a_max, n_s, f_s) if curves is None else curves[:2]
    ax.fill_between(SS, hi, 1e6, color=FILL_TOP, lw=0, zorder=0)
    ax.fill_between(SS, lo, hi, color=FILL_MID, lw=0, zorder=0)
    ax.fill_between(SS, 1e-6, lo, color=FILL_BOT, lw=0, zorder=0)
    ax.plot(SS, hi, "-", color=SLATE, lw=1.2, zorder=3,
            label=r"$B_+ = \max_{p\in\mathcal{P}} B_c(p)$")
    ax.plot(SS, lo, "-", color=BRICK, lw=1.2, zorder=3,
            label=r"$B_- = \min_{p\in\mathcal{P}} B_c(p)$")
    contour_labels = []
    for lev in SPREADS:
        bc = spread_contour(lev, a_min, a_max, n_s, f_s) if curves is None else curves[2]
        if bc.max() <= 0:
            continue
        ax.plot(SS, bc, ls=(0, (1.2, 2.2)), color=CONTOUR, lw=0.9, zorder=2)
        j = int(len(SS) * 0.24)
        if ylim[0] < bc[j] < ylim[1]:
            contour_labels.append((SS[j], bc[j], SS[j - 6], bc[j - 6],
                                   SS[j + 6], bc[j + 6], f"{lev*100:.0f}%"))

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(S_LO, S_HI)
    ax.set_ylim(*ylim)

    for (x, y, x0, y0, x1, y1, txt) in contour_labels:
        k = min(int(np.searchsorted(SS, x)), len(SS) - 1)
        on_band = lo[k] <= y <= hi[k]               # the label's own region colour
        ax.text(x, y, txt, fontsize=6.0, color=CONTOUR, ha="center",
                va="center", rotation=_angle_along(ax, x0, y0, x1, y1),
                rotation_mode="anchor", zorder=4,
                bbox=dict(fc=FILL_MID if on_band else FILL_TOP, ec="none", pad=0.6))

    # region labels: each sits in the visual centre of ITS region; the
    # band label follows the band's own slope
    zc, zm, zk, ze, zp = zones
    ax.text(*zc, labels[0], transform=ax.transAxes,
            fontsize=8.0, ha="center", va="center", color=SLATE_TXT,
            style="italic", zorder=6)
    m = int(np.searchsorted(SS, zm))
    ym = float(np.sqrt(lo[m] * hi[m]))
    ang = _angle_along(ax, SS[m - 8], float(np.sqrt(lo[m - 8] * hi[m - 8])),
                       SS[m + 8], float(np.sqrt(lo[m + 8] * hi[m + 8])))
    ax.text(zm, ym, labels[1], fontsize=6.6,
            ha="center", va="center", color=BAND_TXT, style="italic",
            rotation=ang, rotation_mode="anchor", zorder=6,
            bbox=dict(fc=FILL_MID, ec="none", alpha=0.9, pad=0.3))
    ax.text(*zk, labels[2],
            transform=ax.transAxes, fontsize=8.0, ha="center", va="center",
            color=BRICK_TXT, style="italic", zorder=6)

    # the envelope: a thin double-headed arrow between B_- and B_+ in the
    # boundary colour, the ratio beside it; endpoints live in the caption
    i = int(np.searchsorted(SS, env_x)) - 1
    b_lo, b_hi = lo[i], hi[i]
    ax.annotate("", xy=(env_x, b_hi), xytext=(env_x, b_lo),
                arrowprops=dict(arrowstyle="<|-|>", color=SLATE, lw=1.1,
                                mutation_scale=9, shrinkA=0, shrinkB=0),
                zorder=7)
    ax.text(env_x * 1.18, float(np.sqrt(b_lo * b_hi)),
            f"{a_max / a_min:.2f}$\\times$", fontsize=7.6, color=SLATE_TXT,
            ha="left", va="center", zorder=8)
    ax.text(*zp, p_desc, transform=ax.transAxes, fontsize=6.0,
            va="bottom", ha="left", color="0.30", zorder=6,
            bbox=dict(fc="white", ec="0.82", lw=0.5, alpha=0.92, pad=1.6))
    ax.grid(alpha=0.09, which="both", lw=0.5, zorder=0)
    ax.set_xlabel("MVM row-processing rate $s = 1/t_{\\mathrm{row}}$ "
                  "(Mrows/s)   [faster silicon $\\rightarrow$]")
    ax.set_ylabel("link bandwidth, per direction (GB/s)")
    return lo, hi


def axis_only_chips(ax, chips):
    """A chip whose row rate is known but whose link bandwidth is not
    published gets a marker ON the x axis, not a point at a fabricated
    height."""
    for c in chips:
        s = 1.0 / c.t_mvm_s / 1e6
        ax.plot([s], [0], marker="^", ms=7, mfc=CHIP, mec=CHIP_TXT, mew=0.8,
                transform=ax.get_xaxis_transform(), zorder=8, clip_on=False)
        ax.text(s, 0.03, f"{c.label.split(' (')[0]}\n(row rate only; no link "
                "bandwidth published)", transform=ax.get_xaxis_transform(),
                fontsize=6.0, ha="center", va="bottom", color=CHIP_TXT,
                zorder=8)


def package_A(W, kappa):
    """The seven rules' busiest-resource words at port ratio `kappa`.
    kappa = 1 reads the pinned ladder (bit-identical to recomputation);
    any other kappa recomputes through the evaluator with W.port_ratio.
    The INTRA-die panel never sees kappa: its constants are the A3
    enumeration's own."""
    if kappa == 1.0:
        lad = json.load(open(os.path.join(se.A, "ladder_v0.json")))["table_2p7b"]
        return {n: r["d2d_busiest_words"] for n, r in lad.items()}
    from scripts import search_baselines as sb
    W.port_ratio = kappa
    A = {}
    for n in ("sequential", "clustered", "snake", "random", "least_manhattan",
              "nmap_greedy", "heaviest_first"):
        sc = se.score(sb.generate(n, W, seed=0), W, caliber="single", d2d_gbps=1.0)
        A[n] = sc.per_phase["prefill"]["decomp"]["d2d_busiest_words"]
    del W.port_ratio
    return A


def main():
    W = se.Workload2p7B()
    comp, wr, elw = W.layer_terms_s("prefill")
    L = W.cfg.n_layers
    n_pkg, f_pkg = comp * L, (wr + elw) * L
    A = package_A(W, KAPPA)
    a_min_pkg, a_max_pkg = min(A.values()), max(A.values())
    im = intra_die_model()                          # ffn die, 70 seatings, max model
    a_min_die, a_max_die = min(im["A"]), max(im["A"])
    n_die, f_die = max(im["compute_ref_s"].values()), im["fixed_s"]   # PER-OP compute
    intra_curves = intra_die_curves(SPREADS[0])

    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.0))
    fig.subplots_adjust(left=0.055, right=0.955 if REFS else 0.985, top=0.94,
                        bottom=0.275 if REFS else 0.235, wspace=0.17)

    lo_d, hi_d = draw_panel(
        axes[0], a_min_die, a_max_die, n_die, f_die, (1e-2, 1e3),
        "exhaustive over P; this instance & model",
        "latency object: one die's two co-resident operators\n"
        "(a sub-problem, not the whole model)\n"
        "P = all 70 joint macro seatings, enumerated",
                ((0.20, 0.86), 1.5, (0.80, 0.13), (0.74, 0.86), (0.015, 0.015)),
        15.0, curves=intra_curves, labels=LABELS_MAX)
    axes[0].set_title("(a) Intra-die placement", fontsize=9.5)
    # (the boundaries are the per-op masking thresholds of the max model;
    # the 20% contour is solved on the enumeration under the same model)
    # hardware-derived reference points, at the PUBLISHED per-link rate
    # (no aggregation): HERMES core-to-core link 3.2 Gbit/s = 0.4 GB/s,
    # MVM 133 ns (1-phase) / 520 ns (4-phase); ISAAC's on-chip NoC as an
    # architecture model, 32-bit flit per 1.2 GHz cycle = 4.8 GB/s.
    h1, h4 = 1.0 / 133e-9 / 1e6, 1.0 / 520e-9 / 1e6
    axes[0].plot([h4, h1], [0.4, 0.4], "-", color=CHIP, lw=1.0, zorder=7)
    axes[0].plot([h1], [0.4], marker="D", mfc=CHIP, mec=CHIP_TXT, ms=6.5,
                 mew=0.9, ls="none", zorder=8)
    axes[0].plot([h4], [0.4], marker="D", mfc="white", mec=CHIP, ms=6.5,
                 mew=1.2, ls="none", zorder=8)
    axes[0].text(np.sqrt(h1 * h4), 0.4 / 1.6, "HERMES, 0.4 GB/s\n"
                 "4-phase (open) / 1-phase (filled)", fontsize=6.4,
                 color=CHIP_TXT, ha="center", va="top", zorder=8,
                 linespacing=1.15)
    # ISAAC: the paper's OWN per-link figures, re-read 2026-09-18.
    # Panel (a) = the inter-tile c-mesh link, "a 32-bit link operating at
    # 1 GHz" (Sec. VIII-B) = 4.0 GB/s; panel (b) = the off-chip
    # HyperTransport link of Table I, 6.4 GB/s per link and direction.
    isaac = an.chip("isaac")
    s_is = 1.0 / isaac.t_mvm_s / 1e6
    b_is = isaac.ondie_gbps_per_link
    axes[0].plot([s_is], [b_is], marker="D", mfc=CHIP, mec=CHIP_TXT, ms=6.5,
                 mew=0.9, ls="none", zorder=8)
    axes[0].text(s_is * 1.14, b_is / 1.35,
                 f"ISAAC, {b_is:.1f} GB/s", fontsize=6.4,
                 color=CHIP_TXT, ha="left", va="top", zorder=8,
                 linespacing=1.15)

    lo_p, hi_p = draw_panel(
        axes[1], a_min_pkg, a_max_pkg, n_pkg, f_pkg, (1e-2, 1e3),
        "observed over P: 7 named rules",
        "latency object: whole-model serial prefill (2.7B)\n"
        "P = the seven named die-seating rules"
        + ("" if KAPPA == 1.0 else f"\nports at {KAPPA:g}$\\times$ the link rate"),
        ((0.22, 0.86), 2.1, (0.80, 0.13), (0.98, 0.66), (0.015, 0.015)),
        14.0)
    axes[1].set_title("(b) Inter-die placement", fontsize=9.5)
    # Mythic has no published per-link figure. Default: ONE assumed
    # exploration range as a thin capped line. REFS variant: one projected
    # point, its published 2 GB/s PCIe capability matched to kappa x B.
    for key in ("mythic_m1076",):
        c = an.chip(key)
        sx = 1.0 / c.t_mvm_s / 1e6
        if REFS:
            b_io = c.io_gbps / KAPPA
            axes[1].plot([sx], [b_io], marker="D", mfc="white", mec=CHIP,
                         ms=6.5, mew=1.2, ls="none", zorder=8)
            axes[1].text(sx * 1.18, b_io / 1.45, f"M1076, {b_io:g} GB/s",
                         fontsize=6.4, color=CHIP_TXT, va="center", ha="left",
                         zorder=8, linespacing=1.15)
            continue
        b0, b1 = c.ondie_band
        axes[1].plot([sx, sx], [b0, b1], "-", color=CHIP, lw=1.0, zorder=7)
        axes[1].plot([sx, sx], [b0, b1], marker="D", mfc="white", mec=CHIP,
                     ms=6.5, mew=1.2, ls="none", zorder=8)
        axes[1].text(sx, b0 * 0.70,
                     c.label.split(' (')[0].replace('Mythic AMP ', ''),
                     fontsize=6.4, color=CHIP_TXT, va="top", ha="center",
                     zorder=8)
    # ISAAC's off-chip link IS published (Table I), so it is a point here
    axes[1].plot([s_is], [isaac.d2d_gbps], marker="D", mfc=CHIP, mec=CHIP_TXT,
                 ms=6.5, mew=0.9, ls="none", zorder=8)
    axes[1].text(s_is * 1.14, isaac.d2d_gbps * (1.30 if REFS else 1.10),
                 f"ISAAC, {isaac.d2d_gbps:g} GB/s",
                 fontsize=6.4, color=CHIP_TXT, ha="left", va="bottom",
                 zorder=8, linespacing=1.15)
    # the two configurations this paper's searches actually evaluated:
    # NeuRRAM's device rate with the two interconnect bandwidths
    if REFS:
        # the two bandwidth tiers as muted references across device speeds,
        # run a little past the frame and bracketed outside it with the values
        x_out = S_HI * 1.10                     # the arrow sits here ...
        for bw in (0.4, 12.5):                  # ... and the lines run past it
            axes[1].plot([S_LO, S_HI * 1.16], [bw, bw], color=REF_LINE, lw=0.9,
                         ls=(0, (4, 3)), alpha=0.75, zorder=6, clip_on=False)
        axes[1].annotate("", xy=(x_out, 12.5), xytext=(x_out, 0.4),
                         arrowprops=dict(arrowstyle="<|-|>", color=SLATE, lw=1.1,
                                         mutation_scale=9, shrinkA=0, shrinkB=0),
                         zorder=6, annotation_clip=False)
        axes[1].text(x_out * 1.11, np.sqrt(0.4 * 12.5), "Reference bandwidth span",
                     fontsize=6.6, color=SLATE_TXT, ha="center", va="top",
                     rotation=90, rotation_mode="anchor", zorder=9, clip_on=False)
        for bw in (0.4, 12.5):
            axes[1].text(S_HI / 1.08, bw * 1.12, f"{bw:g} GB/s", fontsize=6.4,
                         color=REF_TXT, ha="right", va="bottom", zorder=9)
        # ... and the two configurations evaluated here, at one device rate
        axes[1].plot([S_REF, S_REF], [0.4, 12.5], "-", color=CHIP, lw=1.0, zorder=8)
    for bw in (0.4, 12.5):
        axes[1].plot([S_REF], [bw], marker="o", mfc="white", mec=CHIP,
                     ms=7, mew=1.5, ls="none", alpha=1.0, zorder=9)
        if REFS:
            up = bw > 1
            # left-aligned so the point sits under the middle of "NeuRRAM"
            axes[1].text(S_REF / 1.21, bw * 1.35 if up else bw / 1.35,
                         f"NeuRRAM, {bw:g} GB/s", fontsize=6.4,
                         color=CHIP_TXT, ha="left", va="bottom" if up else "top",
                         zorder=9, linespacing=1.15)
        else:
            axes[1].text(S_REF / 1.22, bw if bw > 1 else bw / 1.45,
                         f"NeuRRAM-based\n{bw:g} GB/s", fontsize=6.4,
                         color=CHIP_TXT, ha="right", va="center", zorder=9,
                         linespacing=1.15)

    h, lab = axes[0].get_legend_handles_labels()
    extra = [plt.Line2D([], [], ls=(0, (1.2, 2.2)), color=CONTOUR, lw=0.9),
             plt.Line2D([], [], marker="D", ls="none", mfc=CHIP, mec=CHIP_TXT,
                        ms=6),
             plt.Line2D([], [], marker="D", ls="none" if REFS else "-", color=CHIP,
                        mfc="white", mec=CHIP, mew=1.2, ms=6, lw=1.0),
             plt.Line2D([], [], marker="o", ls="-" if REFS else "none", color=CHIP,
                        mfc="white", mec=CHIP, mew=1.5, ms=7, lw=1.0)]
    if REFS:
        lines = [plt.Line2D([], [], color=SLATE, lw=1.2),
                 plt.Line2D([], [], ls=(0, (1.2, 2.2)), color=CONTOUR, lw=0.9),
                 plt.Line2D([], [], ls=(0, (4, 3)), color=REF_LINE, lw=0.9, alpha=0.75)]
        marks = [plt.Line2D([], [], marker="D", ls="none", mfc=CHIP, mec=CHIP_TXT, ms=6),
                 plt.Line2D([], [], marker="D", ls="none", mfc="white", mec=CHIP, mew=1.2, ms=6),
                 plt.Line2D([], [], marker="o", ls="-", color=CHIP, mfc="white", mec=CHIP,
                            mew=1.5, ms=7, lw=1.0)]
        fig.legend(lines + marks, [
            r"boundaries $B_-$, $B_+$: min and max of $B_c(p)$ over the placement set",
            "placement latency spread, 20%",
            "the two evaluated bandwidth tiers",
            "published parameter, projected onto this instance",
            "derived or alternative-mode value, projected the same way",
            "configurations evaluated in this paper"],
            loc="lower center", ncol=2, fontsize=6.8, frameon=False,
            bbox_to_anchor=(0.5, -0.012), labelspacing=0.9, columnspacing=2.5,
            handlelength=2.4, handletextpad=0.8)
    else:
      fig.legend(h + extra, lab + [
        r"placement latency spread $(T_{\max}-T_{\min})/T_{\min}$ over the same $\mathcal{P}$",
        "hardware-derived reference point (published parameters projected "
        "onto this instance)",
        ("M1076: published 2 GB/s I/O capability matched to the model's port "
         "capacity $\\kappa B$, a projection" if REFS else
         "assumed bandwidth range (no per-link figure published)"),   # Mythic only
        ("NeuRRAM-based: the two bandwidth configurations evaluated in this paper, "
         "at one device rate" if REFS else
         "systems evaluated in this paper: NeuRRAM device rate, the two "
         "interconnect bandwidths")]
        + (["0.4 and 12.5 GB/s: the two bandwidth tiers, across device speeds"] if REFS else []),
        loc="lower center", ncol=2, fontsize=6.8, frameon=False,
        bbox_to_anchor=(0.5, -0.012))
    fig.savefig(OUT_PNG, dpi=150)
    fig.savefig(OUT_PDF)   # vector version, same figure
    print(f"figure -> {OUT_PNG}")

    data = {"kappa": KAPPA, "note": "Isobar Fig.1 rebuild; both axes rates; regions from "
                    "placement extrema; R includes the non-scaling terms; "
                    "spread contours over the same P",
            "s_ref_mrows_s": S_REF, "spread_contours": list(SPREADS),
                        "within_die": {"quantifier": "certified (exhaustive, 70 seatings "
                           "of the ffn die)",
                           "model": "per-op max(compute, serialization/B); boundaries = "
                                    "masking thresholds against the PER-OP compute; spread "
                                    "contour solved on the enumeration under the same model",
                           "compute_per_op_ref_s": n_die, "a_min_words": a_min_die,
                           "a_max_words": a_max_die,
                           "ratio": a_max_die / a_min_die,
                           "n_scaling_s": n_die, "fixed_s": f_die,
                                                      "B_minus_at_ref_gbps": float(np.interp(S_REF, SS, lo_d)),
                           "B_plus_at_ref_gbps": float(np.interp(S_REF, SS, hi_d)),
                           "B_spread20_at_ref_gbps": float(np.interp(S_REF, SS, intra_curves[2])),
                           "physical_points": {str(b): ("below B- (communication dominated)"
                                                        if b < float(np.interp(S_REF, SS, lo_d)) else
                                                        "above B+ (compute dominated)"
                                                        if b > float(np.interp(S_REF, SS, hi_d)) else
                                                        "inside the band") for b in (0.4, 2.0)}},
            "package": {"quantifier": "observed over P (7 named seatings)",
                        "a_min_words": a_min_pkg, "a_max_words": a_max_pkg,
                        "a_min_rule": min(A, key=A.get),
                        "a_max_rule": max(A, key=A.get),
                        "ratio": a_max_pkg / a_min_pkg,
                        "n_scaling_s": n_pkg, "fixed_s": f_pkg,
                        "B_minus_at_ref_gbps": float(np.interp(S_REF, SS, lo_p)),
                        "B_plus_at_ref_gbps": float(np.interp(S_REF, SS, hi_p))}}
    bm, bp = data["package"]["B_minus_at_ref_gbps"], data["package"]["B_plus_at_ref_gbps"]
    data["package"]["physical_points"] = {
        str(b): ("below B- (communication dominated)" if b < bm else
                 "above B+ (compute / fixed-cost dominated)" if b > bp else "inside the band")
        for b in (0.4, 12.5)}
    json.dump(data, open(OUT_JSON, "w"), indent=1)
    print(f"data -> {OUT_JSON}")
    print("  physical points:", data["package"]["physical_points"])
    for k in ("within_die", "package"):
        d = data[k]
        print(f"  {k:11} A ratio {d['ratio']:.3f}; at the reference rate "
              f"B_- {d['B_minus_at_ref_gbps']:.3f} .. B_+ "
              f"{d['B_plus_at_ref_gbps']:.3f} GB/s")


if __name__ == "__main__":
    main()
