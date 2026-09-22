"""The Isobar Fig.1 at the paper's double-column width -- a SEPARATE
output (analysis/phase_diagram_isobar_print.png); the reviewed
analysis/phase_diagram_isobar.png is not touched.

Differences from the large version, per the review: the two instance
boxes move to the caption (analysis/phase_diagram_isobar_caption.md),
the figure keeps only '70 placements' / '7 placement rules'; the legend
is three chip entries plus the boundary and contour definitions; every
piece of text is set at 7-8 pt AT FINAL SIZE (the figure is drawn at
7.16 x 3.2 in, not scaled down), so captions are shortened rather than
shrunk.

    python3 scripts/fig_phase_isobar_print.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts import anchors as an
from scripts import search_eval as se
from scripts.fig_phase_isobar import (boundaries, spread_contour, _angle_along,
                                      intra_die_model, intra_die_curves,
                                      SS, S_LO, S_HI, S_REF, SLATE, SLATE_TXT,
                                      BRICK, BRICK_TXT, FILL_TOP, FILL_MID,
                                      FILL_BOT, BAND_TXT, CHIP, CHIP_TXT,
                                      CONTOUR)

from scripts.fig_phase_isobar import KAPPA, package_A, _SFX, REF_LINE, REF_TXT
OUT_PNG = os.path.join(se.A, f"phase_diagram_isobar_print{_SFX}.png")
OUT_PDF = os.path.join(se.A, f"phase_diagram_isobar_print{_SFX}.pdf")
matplotlib.rcParams["pdf.fonttype"] = 42   # embed TrueType: text stays text in the PDF
WIDTH_IN, HEIGHT_IN = 7.16, 3.35             # double column
FS = dict(title=8.5, axis=8.0, tick=7.0, text=7.0, legend=7.0, ratio=7.5)
SPREAD = 0.20


LABELS_SUM = ("compute / fixed-cost\ndominated", "placement decides",
              "communication\ndominated")
LABELS_MAX = ("communication\nmasked", "placement decides",
              "communication\nexposed")


def panel(ax, a_min, a_max, n_s, f_s, ylim, zones, env_x, short, curves=None,
          labels=LABELS_SUM):
    lo, hi = boundaries(a_min, a_max, n_s, f_s) if curves is None else curves[:2]
    ax.fill_between(SS, hi, 1e6, color=FILL_TOP, lw=0, zorder=0)
    ax.fill_between(SS, lo, hi, color=FILL_MID, lw=0, zorder=0)
    ax.fill_between(SS, 1e-6, lo, color=FILL_BOT, lw=0, zorder=0)
    ax.plot(SS, hi, "-", color=SLATE, lw=1.0, zorder=3,
            label=r"$B_+ = \max_{p\in\mathcal{P}} B_c(p)$")
    ax.plot(SS, lo, "-", color=BRICK, lw=1.0, zorder=3,
            label=r"$B_- = \min_{p\in\mathcal{P}} B_c(p)$")
    bc = spread_contour(SPREAD, a_min, a_max, n_s, f_s) if curves is None else curves[2]
    ax.plot(SS, bc, ls=(0, (1.2, 2.2)), color=CONTOUR, lw=0.8, zorder=2,
            label="placement latency spread, 20%")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(S_LO, S_HI)
    ax.set_ylim(*ylim)
    j = int(len(SS) * 0.24)
    ax.text(SS[j], bc[j], "20%", fontsize=FS["text"], color=CONTOUR,
            ha="center", va="center", zorder=4, rotation_mode="anchor",
            rotation=_angle_along(ax, SS[j - 6], bc[j - 6], SS[j + 6], bc[j + 6]),
            bbox=dict(fc=FILL_TOP, ec="none", pad=0.5))
    zc, zm, zk, zs = zones
    ax.text(*zc, labels[0], transform=ax.transAxes,
            fontsize=FS["text"], ha="center", va="center", color=SLATE_TXT,
            style="italic", zorder=6, linespacing=1.1)
    m = int(np.searchsorted(SS, zm))
    ax.text(zm, float(np.sqrt(lo[m] * hi[m])), labels[1],
            fontsize=FS["text"], ha="center", va="center", color=BAND_TXT,
            style="italic", zorder=6, rotation_mode="anchor",
            rotation=_angle_along(ax, SS[m - 8], float(np.sqrt(lo[m - 8] * hi[m - 8])),
                                  SS[m + 8], float(np.sqrt(lo[m + 8] * hi[m + 8]))),
            bbox=dict(fc=FILL_MID, ec="none", alpha=0.9, pad=0.3))
    ax.text(*zk, labels[2], transform=ax.transAxes,
            fontsize=FS["text"], ha="center", va="center", color=BRICK_TXT,
            style="italic", zorder=6, linespacing=1.1)
    i = int(np.searchsorted(SS, env_x)) - 1
    ax.annotate("", xy=(env_x, hi[i]), xytext=(env_x, lo[i]),
                arrowprops=dict(arrowstyle="<|-|>", color=SLATE, lw=0.9,
                                mutation_scale=7, shrinkA=0, shrinkB=0),
                zorder=7)
    ax.text(env_x * 1.2, float(np.sqrt(lo[i] * hi[i])),
            f"{a_max / a_min:.2f}$\\times$", fontsize=FS["ratio"],
            color=SLATE_TXT, ha="left", va="center", zorder=8)
    ax.text(*zs, short, transform=ax.transAxes, fontsize=FS["text"],
            ha="left", va="bottom", color="0.30", zorder=6)
    ax.grid(alpha=0.09, which="both", lw=0.4, zorder=0)
    ax.tick_params(labelsize=FS["tick"], length=2.5, pad=2)
    ax.set_xlabel(r"MVM row rate $s = 1/t_{\mathrm{row}}$ (Mrows/s)",
                  fontsize=FS["axis"], labelpad=2)
    return lo, hi


def main():
    W = se.Workload2p7B()
    comp, wr, elw = W.layer_terms_s("prefill")
    L = W.cfg.n_layers
    n_pkg, f_pkg = comp * L, (wr + elw) * L
    A = package_A(W, KAPPA)
    a_min_pkg, a_max_pkg = min(A.values()), max(A.values())
    im = intra_die_model()
    a_min_die, a_max_die = min(im["A"]), max(im["A"])
    n_die, f_die = max(im["compute_ref_s"].values()), im["fixed_s"]
    intra_curves = intra_die_curves(SPREAD)

    fig, axes = plt.subplots(1, 2, figsize=(WIDTH_IN, HEIGHT_IN))
    fig.subplots_adjust(left=0.075, right=0.955, top=0.92, bottom=0.30,
                        wspace=0.14)

    panel(axes[0], a_min_die, a_max_die, n_die, f_die, (1e-2, 1e3),
                    ((0.22, 0.85), 1.5, (0.82, 0.10), (0.02, 0.02)), 6.0,
          "70 placements", curves=intra_curves, labels=LABELS_MAX)
    axes[0].set_title("(a) Intra-die placement", fontsize=FS["title"], pad=4)
    axes[0].set_ylabel("link bandwidth per direction (GB/s)",
                       fontsize=FS["axis"], labelpad=2)
    h1, h4 = 1.0 / 133e-9 / 1e6, 1.0 / 520e-9 / 1e6
    axes[0].plot([h4, h1], [0.4, 0.4], "-", color=CHIP, lw=0.8, zorder=7)
    axes[0].plot([h1], [0.4], marker="D", mfc=CHIP, mec=CHIP_TXT, ms=5,
                 mew=0.7, ls="none", zorder=8)
    axes[0].plot([h4], [0.4], marker="D", mfc="white", mec=CHIP, ms=5,
                 mew=1.0, ls="none", zorder=8)
    axes[0].text(np.sqrt(h1 * h4), 0.4 / 1.6, "HERMES\n4-phase (open) / "
                 "1-phase (filled)", fontsize=FS["text"], color=CHIP_TXT,
                 ha="center", va="top", zorder=8, linespacing=1.1)
    isaac = an.chip("isaac")
    s_is = 1.0 / isaac.t_mvm_s / 1e6
    b_is = isaac.ondie_gbps_per_link          # inter-tile c-mesh link, 4.0 GB/s
    axes[0].plot([s_is], [b_is], marker="D", mfc=CHIP, mec=CHIP_TXT, ms=5,
                 mew=0.7, ls="none", zorder=8)
    axes[0].text(s_is * 1.15, b_is / 1.35, "ISAAC", fontsize=FS["text"],
                 color=CHIP_TXT, ha="left", va="top", zorder=8)

    panel(axes[1], a_min_pkg, a_max_pkg, n_pkg, f_pkg, (1e-2, 1e3),
          ((0.22, 0.85), 3.2, (0.80, 0.15), (0.02, 0.02)), 14.0,
          "7 placement rules")
    axes[1].set_title("(b) Inter-die placement", fontsize=FS["title"], pad=4)
    axes[1].tick_params(labelleft=False)
    # M1076: its published 2 GB/s I/O capability matched to kappa x B
    c = an.chip("mythic_m1076")
    sx, b_io = 1.0 / c.t_mvm_s / 1e6, c.io_gbps / KAPPA
    axes[1].plot([sx], [b_io], marker="D", mfc="white", mec=CHIP, ms=5, mew=1.0,
                 ls="none", zorder=8)
    axes[1].text(sx * 1.10, b_io / 1.75, "M1076", fontsize=FS["text"],
                 color=CHIP_TXT, va="center", ha="left", zorder=8)
    # the two bandwidth tiers across device speeds, bracketed outside the frame
    x_out = S_HI * 1.10
    for bw in (0.4, 12.5):
        axes[1].plot([S_LO, S_HI * 1.16], [bw, bw], color=REF_LINE, lw=0.8,
                     ls=(0, (4, 3)), alpha=0.75, zorder=6, clip_on=False)
        axes[1].text(S_HI / 1.08, bw * 1.12, f"{bw:g} GB/s", fontsize=FS["text"],
                     color=REF_TXT, ha="right", va="bottom", zorder=9)
    axes[1].annotate("", xy=(x_out, 12.5), xytext=(x_out, 0.4),
                     arrowprops=dict(arrowstyle="<|-|>", color=SLATE, lw=0.9,
                                     mutation_scale=7, shrinkA=0, shrinkB=0),
                     zorder=6, annotation_clip=False)
    axes[1].text(x_out * 1.11, np.sqrt(0.4 * 12.5), "Reference bandwidth span",
                 fontsize=FS["text"], color=SLATE_TXT, ha="center", va="top",
                 rotation=90, rotation_mode="anchor", zorder=9, clip_on=False)
    axes[1].plot([S_REF, S_REF], [0.4, 12.5], "-", color=CHIP, lw=0.8, zorder=8)
    # ISAAC's off-chip HyperTransport link is published (Table I)
    axes[1].plot([s_is], [isaac.d2d_gbps], marker="D", mfc=CHIP, mec=CHIP_TXT,
                 ms=5, mew=0.7, ls="none", zorder=8)
    axes[1].text(s_is * 1.15, isaac.d2d_gbps * 1.10, "ISAAC",
                 fontsize=FS["text"], color=CHIP_TXT, ha="left", va="bottom",
                 zorder=8)
    for bw in (0.4, 12.5):
        axes[1].plot([S_REF], [bw], marker="o", mfc="white", mec=CHIP, ms=5.5,
                     mew=1.2, ls="none", zorder=9)
        up = bw > 1
        axes[1].text(S_REF, bw * 1.35 if up else bw / 1.35, f"NeuRRAM\n{bw:g} GB/s",
                     fontsize=FS["text"], color=CHIP_TXT, ha="center",
                     va="bottom" if up else "top", zorder=9, linespacing=1.1)

    lines = [plt.Line2D([], [], color=SLATE, lw=1.0),
             plt.Line2D([], [], ls=(0, (1.2, 2.2)), color=CONTOUR, lw=0.8),
             plt.Line2D([], [], ls=(0, (4, 3)), color=REF_LINE, lw=0.8, alpha=0.75)]
    marks = [plt.Line2D([], [], marker="D", ls="none", mfc=CHIP, mec=CHIP_TXT, ms=5),
             plt.Line2D([], [], marker="D", ls="none", mfc="white", mec=CHIP, mew=1.0, ms=5),
             plt.Line2D([], [], marker="o", ls="-", color=CHIP, mfc="white", mec=CHIP,
                        mew=1.2, ms=5.5, lw=0.8)]
    fig.legend(lines + marks, [r"boundaries $B_-$, $B_+$ over the placement set",
                               "placement latency spread, 20%",
                               "the two evaluated bandwidth tiers",
                               "published parameter, projected onto this instance",
                               "derived or alternative-mode value",
                               "configurations evaluated in this paper"],
               loc="lower center", ncol=2, fontsize=FS["legend"],
               frameon=False, bbox_to_anchor=(0.5, -0.005),
               handlelength=2.0, columnspacing=2.0, labelspacing=0.6)
    fig.savefig(OUT_PNG, dpi=300)
    fig.savefig(OUT_PDF)   # vector version, same figure
    print(f"figure -> {OUT_PNG}  ({WIDTH_IN} x {HEIGHT_IN} in, text 7-8 pt)")


if __name__ == "__main__":
    main()
