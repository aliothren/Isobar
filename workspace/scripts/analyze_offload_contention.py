"""Scenario B (attention offloaded) versions of the contention results.

Everything so far (contention_system, d2d_impact) is scenario A: attention on
chip, K/V write included. Offloading attention changes the two shields that
kept the network invisible:

  * prefill: each die's compute per layer SHRINKS (13.11 -> 8.44 ms of stage),
    so there is less compute to hide transfers behind -- every knee moves UP.
  * decode: the serial K/V write (90% of a decode step) LEAVES the chip with
    the attention -- the shield that made decode "untouchable" is gone, and
    on-die contention reaches decode for the first time.

All closed-form: per-op compute/write/serialization come from
analysis/contention_system.json (real mapper runs); scenario-B stacks keep
only the static ops (qkv_proj / out_proj / ffn1 / ffn2), matching
analyze_system_gpt2's B accounting (on-chip side only; the receiving unit and
the die<->unit traffic are NOT modeled -- same stated caveat as scenario B
everywhere else).

Usage (container): python3 scripts/analyze_offload_contention.py
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")

OUT = "/home/workspace/analysis"
STATIC = {"qkv_proj", "out_proj", "ffn1", "ffn2"}
N_LAYERS = 24
WORDS = 512 * 1024                      # one boundary, prefill (S x d_model)
WORDS_DEC = 1024                        # decode boundary (d_model)
CYC = 1.449e-6

# busiest-wire integers per D2D assignment (pinned in test_d2d.py)
D2D = [("snake", 1), ("sequential rows", 2), ("far pairs (adversarial)", 6),
       ("bus (shared interposer)", 23)]
BWS = [64.0, 256.0, 1024.0]


def stack_B(per_op):
    """Scenario-B stack: static ops only, write gone with the attention."""
    return N_LAYERS * sum(max(o["compute_s"], o["serial_s"])
                          for o in per_op if o["name"] in STATIC)


def main():
    with open(os.path.join(OUT, "contention_system.json")) as f:
        sysd = json.load(f)

    out = {"note": "scenario B = attention offloaded, on-chip side only",
           "phases": {}}
    for phase, wds in (("prefill", WORDS), ("decode", WORDS_DEC)):
        d = sysd["phases"][phase]
        sf_B = N_LAYERS * sum(max(o["compute_s"], 0.0)
                              for o in next(iter(d["per_op"].values()))
                              if o["name"] in STATIC)
        print(f"=== {phase}, scenario B: stall-free stack "
              f"{sf_B*1e3:.3f} ms (A was {d['stall_free_s']*1e3:.2f} ms) ===")
        rows = {}
        for label, per_op in d["per_op"].items():
            tot = stack_B(per_op)
            rows[label] = {"latency_s": tot, "mult": tot / sf_B}
            print(f"  {label:22} {tot*1e3:9.3f} ms   {tot/sf_B:5.2f}x"
                  f"   (A was {d['rows'][[r['label'] for r in d['rows']].index(label)]['mult']:.2f}x)")
        out["phases"][phase] = {"stall_free_B_s": sf_B, "on_die": rows}
        print()

    # ---------------- D2D pipelined, scenario B stage
    pre = out["phases"]["prefill"]["stall_free_B_s"]
    stage_B = pre / N_LAYERS
    stage_A = sysd["phases"]["prefill"]["stall_free_s"] / N_LAYERS
    print(f"=== D2D pipelined, prefill: stage A {stage_A*1e3:.2f} ms -> "
          f"B {stage_B*1e3:.2f} ms (less compute to hide behind) ===")
    print(f"{'assignment':26}" + "".join(f"{f'@{b:,.0f} w/c':>14}" for b in BWS))
    d2d_out = {}
    for label, busiest in D2D:
        cells = []
        for bw in BWS:
            beat = max(stage_B, busiest * WORDS / bw * CYC)
            cells.append(beat / stage_B)
        d2d_out[label] = dict(zip((str(int(b)) for b in BWS), cells))
        print(f"  {label:24}" + "".join(f"{c:>13.2f}x" for c in cells))

    # decode D2D under B: stage shrinks ~15x, boundary tiny -- check anyway
    dec = out["phases"]["decode"]["stall_free_B_s"]
    stage_dB = dec / N_LAYERS
    print(f"\n  decode stage B {stage_dB*1e6:.1f} us; sequential boundary beat at "
          f"64 w/c = {2*WORDS_DEC/64*CYC*1e6:.1f} us -> "
          f"{max(stage_dB, 2*WORDS_DEC/64*CYC)/stage_dB:.2f}x "
          "(decode is now touchable too)")
    out["d2d_prefill_B"] = {"stage_B_s": stage_B, "table": d2d_out}
    out["decode_stage_B_s"] = stage_dB

    with open(os.path.join(OUT, "offload_contention.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("\nJSON -> offload_contention.json")
    make_figure(sysd, out)
    make_placement_figures(sysd, out)


def make_figure(sysd, out):
    """One 3-panel figure, one question per panel:
      (1) prefill: everything gets faster, the SPREAD between schemes stays;
      (2) decode: the write block was the shield -- remove it and the network
          differences surface (stacked bars make the shield visible);
      (3) pipelined throughput: the offload dividend exists only where the
          package network is not the bottleneck.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    ORDER = ["star (private links)", "mesh, glb centre", "mesh, glb corner",
             "h-tree (k=4)", "bus (shared medium)"]
    SHORT = ["ideal\n(no queue)", "star", "mesh\ncentre", "mesh\ncorner",
             "h-tree", "bus"]
    C_ON, C_OFF, C_WR = "#8fa8bf", "#2a9d8f", "#d9c5a0"

    pre_A, dec_A = sysd["phases"]["prefill"], sysd["phases"]["decode"]
    mult_A = {r["label"]: r["latency_s"] for r in pre_A["rows"]}
    multd_A = {r["label"]: r["latency_s"] for r in dec_A["rows"]}
    pre_B = out["phases"]["prefill"]["on_die"]
    dec_B = out["phases"]["decode"]["on_die"]
    write_dec = dec_A["write_s"]

    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.6))

    # ---- (1) prefill request latency
    ax = axes[0]
    on = [pre_A["stall_free_s"]] + [mult_A[k] for k in ORDER]
    off = [out["phases"]["prefill"]["stall_free_B_s"]] +           [pre_B[k]["latency_s"] for k in ORDER]
    x = np.arange(len(SHORT))
    ax.bar(x - 0.19, [v * 1e3 for v in on], 0.36, color=C_ON,
           label="attention on chip")
    ax.bar(x + 0.19, [v * 1e3 for v in off], 0.36, color=C_OFF,
           label="attention offloaded")
    ax.set_xticks(x); ax.set_xticklabels(SHORT, fontsize=8.5)
    ax.set_ylabel("one prefill request (ms)")
    ax.set_title("Prefill: everything speeds up,\nthe scheme spread stays",
                 fontsize=10)
    ax.legend(fontsize=8); ax.grid(alpha=0.25, axis="y")

    # ---- (2) decode token latency, write stacked
    ax = axes[1]
    rest_on = [dec_A["stall_free_s"] - write_dec] +               [multd_A[k] - write_dec for k in ORDER]
    off = [out["phases"]["decode"]["stall_free_B_s"]] +           [dec_B[k]["latency_s"] for k in ORDER]
    ax.bar(x - 0.19, [write_dec * 1e3] * len(SHORT), 0.36, color=C_WR,
           label="K/V write (the shield)")
    ax.bar(x - 0.19, [v * 1e3 for v in rest_on], 0.36,
           bottom=[write_dec * 1e3] * len(SHORT), color=C_ON,
           label="compute + network")
    ax.bar(x + 0.19, [v * 1e3 for v in off], 0.36, color=C_OFF,
           label="attention offloaded")
    for i, v in enumerate(off):
        ax.text(i + 0.19, v * 1e3 + 0.3, f"{v*1e3:.1f}", ha="center",
                fontsize=8, color=C_OFF, fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels(SHORT, fontsize=8.5)
    ax.set_ylabel("one decode token (ms)")
    ax.set_title("Decode: the write block hid the network;\n"
                 "offload removes it and 3x appears", fontsize=10)
    ax.legend(fontsize=8); ax.grid(alpha=0.25, axis="y")

    # ---- (3) pipelined throughput at 64 w/c
    ax = axes[2]
    CYC, WORDS = 1.449e-6, 512 * 1024
    # FEASIBLE 48-die configuration (two dies per layer): stage = the slower
    # half-layer; busiest-wire integers from the 6x8 chain (snake 1,
    # sequential 2, far pairs 8, bus 47). Read at a LOW example input
    # (64 w/c ~ 0.044 GB/s) -- measured D2D links sit two orders higher, so
    # this panel illustrates the mechanism, not an expected operating point.
    perh = pre_A["per_op"]["mesh, glb centre"]
    attn_h = sum(o["compute_s"] + o["write_s"] for o in perh
                 if o["name"] in ("qkv_proj", "qk^t", "av", "out_proj"))
    ffn_h = sum(o["compute_s"] + o["write_s"] for o in perh
                if o["name"] in ("ffn1", "ffn2"))
    stage_A = max(attn_h, ffn_h)
    stage_B = max(attn_h - sum(o["write_s"] + o["compute_s"] for o in perh
                               if o["name"] in ("qk^t", "av")), ffn_h)
    labels3 = ["ideal\nnetwork", "snake", "sequential", "far pairs\n(worst)",
               "bus"]
    busiest = [0, 1, 2, 8, 47]
    def thr(stage, b):
        net = b * WORDS / 64.0 * CYC
        return 1.0 / max(stage, net)
    on = [thr(stage_A, b) for b in busiest]
    off = [thr(stage_B, b) for b in busiest]
    x3 = np.arange(len(labels3))
    ax.bar(x3 - 0.19, on, 0.36, color=C_ON, label="attention on chip")
    ax.bar(x3 + 0.19, off, 0.36, color=C_OFF, label="attention offloaded")
    ax.axhline(1.0 / stage_B, color=C_OFF, ls="--", lw=1.2)
    ax.text(1.55, 1.0 / stage_B - 9, "what offload SHOULD deliver",
            fontsize=8, color=C_OFF, ha="left")
    ax.set_ylim(0, 1.0 / stage_B * 1.18)
    for i, (a_, b_) in enumerate(zip(on, off)):
        gain = (b_ - a_) / a_ * 100
        ax.text(i + 0.19, b_ + 2, f"+{gain:.0f}%" if gain >= 1 else "+0%",
                ha="center", fontsize=8.5, fontweight="bold",
                color="#b33f2b" if gain < 1 else "#1c6b60")
    ax.set_xticks(x3); ax.set_xticklabels(labels3, fontsize=8.5)
    ax.set_ylabel("pipelined throughput (requests/s)\n@64 w/c EXAMPLE input (48-die config)")
    ax.set_title("The offload dividend (+55%) is paid out\n"
                 "only where the package network is not the bottleneck",
                 fontsize=10)
    ax.legend(fontsize=8, loc="center right"); ax.grid(alpha=0.25, axis="y")

    fig.suptitle("Offloading attention removes the two shields that kept the "
                 "network invisible", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    path = os.path.join(OUT, "offload_contention.png")
    fig.savefig(path, dpi=130); plt.close(fig)
    print(f"PNG -> {path}")




def make_placement_figures(sysd, out):
    """Two STANDALONE figures -- one per operating condition (attention on
    chip / offloaded) -- each showing what PLACEMENT does in that world.
    Deliberately the same three-panel layout so either one reads alone:

      (1) within the die: where the glb sits  -> one request's latency
          (prefill moves; decode's bars sit beside it to show it does not);
      (2) across dies: which die holds which layer -> pipelined throughput;
      (3) the SAME choices, priced in energy -> flat bars, full scale,
          no axis zoom (zooming would manufacture an effect that is not there).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from scripts import fabric as fabric_mod
    from scripts import llm_workload as lw

    CYC, WORDS = 1.449e-6, 512 * 1024
    fabM = fabric_mod.from_yaml("/home/workspace/models/fabric/mlx300_multidie.yaml")
    cfg = lw.GptConfig()
    mx = fabM.level("die").mesh[0]
    snake = [ (L // mx) * mx + (mx - 1 - (L % mx) if (L // mx) % 2 else L % mx)
              for L in range(cfg.n_layers) ]
    far = [L // 2 if L % 2 == 0 else 23 - L // 2 for L in range(cfg.n_layers)]
    ASG = [("snake", snake, 1), ("sequential\nrows", None, 2),
           ("far pairs\n(worst)", far, 6)]
    surplus = [lw.die_to_die_activation(cfg, 512, "prefill", fabric=fabM,
                                        assignment=a)["energy_J"]
               for _, a, _ in ASG]

    with open(os.path.join(OUT, "gpt2_system_totals_prefill.json")) as f:
        totals = json.load(f)["scenarios"]

    pre_A = {r["label"]: r["latency_s"] for r in sysd["phases"]["prefill"]["rows"]}
    dec_A = {r["label"]: r["latency_s"] for r in sysd["phases"]["decode"]["rows"]}
    pre_B = {k: v["latency_s"] for k, v in out["phases"]["prefill"]["on_die"].items()}
    dec_B = {k: v["latency_s"] for k, v in out["phases"]["decode"]["on_die"].items()}
    stage_A = sysd["phases"]["prefill"]["stall_free_s"] / cfg.n_layers
    stage_B = out["d2d_prefill_B"]["stage_B_s"]

    CASES = [
        ("onchip", "attention ON chip",
         pre_A["mesh, glb centre"], pre_A["mesh, glb corner"],
         dec_A["mesh, glb centre"], dec_A["mesh, glb corner"],
         stage_A, totals["A_E"]),
        ("offload", "attention OFFLOADED",
         pre_B["mesh, glb centre"], pre_B["mesh, glb corner"],
         dec_B["mesh, glb centre"], dec_B["mesh, glb corner"],
         stage_B, totals["B_E"]),
    ]
    TEAL, SLATE, RED, GREY = "#2a9d8f", "#8fa8bf", "#d1495b", "#c9d2d9"

    for key, world, pc, pk, dc, dk, stage, base_E in CASES:
        fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.7))

        # ---- (1) glb position -> one request / one token
        ax = axes[0]
        ax.bar([0, 1], [pc * 1e3, pk * 1e3], 0.62,
               color=[TEAL, RED])
        for i, v in enumerate((pc, pk)):
            ax.text(i, v * 1e3 * 1.02, f"{v*1e3:.0f} ms", ha="center",
                    fontsize=10, fontweight="bold")
        ax.text(0.27, 0.955, f"x{pk/pc:.2f} from the floorplan alone",
                transform=ax.transAxes, ha="center", fontsize=10, color=RED,
                fontweight="bold")
        ax.set_ylim(0, max(pc, pk) * 1e3 * 1.32)
        ax.set_ylabel("one prefill request (ms)")
        ax2 = ax.twinx()
        ax2.bar([2.4, 3.4], [dc * 1e3, dk * 1e3], 0.62, color=[GREY, GREY],
                edgecolor="0.5")
        for i, v in zip((2.4, 3.4), (dc, dk)):
            ax2.text(i, v * 1e3 * 1.03, f"{v*1e3:.2f}", ha="center",
                     fontsize=9, color="0.35")
        ax2.text(2.9, max(dc, dk) * 1e3 * 1.16, "decode: immune",
                 ha="center", fontsize=9.5, color="0.35")
        ax2.set_ylim(0, max(dc, dk) * 1e3 * 1.32)
        ax2.set_ylabel("one decode token (ms)", color="0.4")
        ax2.tick_params(axis="y", labelcolor="0.4")
        ax.set_xticks([0, 1, 2.4, 3.4])
        ax.set_xticklabels(["glb at\ncentre", "glb at\ncorner",
                            "glb at\ncentre", "glb at\ncorner"], fontsize=9)
        ax.set_title("WITHIN the die: where the glb sits\n"
                     "(same mesh, same traffic, same mapping)", fontsize=10)
        ax.grid(alpha=0.25, axis="y")

        # ---- (2) layer->die assignment -> throughput
        ax = axes[1]
        thr = [1.0 / max(stage, b * WORDS / 64.0 * CYC) for _, _, b in ASG]
        ideal = 1.0 / stage
        ax.axhline(ideal, color="0.55", ls="--", lw=1.2)
        ax.text(2.45, ideal * 1.03, "ideal network", fontsize=8.5,
                color="0.45", ha="right")
        ax.bar(range(3), thr, 0.6, color=[TEAL, SLATE, RED])
        for i, v in enumerate(thr):
            ax.text(i, v + ideal * 0.02, f"{v:.1f}", ha="center", fontsize=10,
                    fontweight="bold")
        ax.text(1, ideal * 1.15, f"x{thr[0]/thr[2]:.1f} from the assignment "
                "alone", ha="center", fontsize=10, color=RED,
                fontweight="bold")
        ax.set_ylim(0, ideal * 1.28)
        ax.set_xticks(range(3))
        ax.set_xticklabels([n for n, _, _ in ASG], fontsize=9)
        ax.set_ylabel("pipelined throughput (requests/s)")
        ax.set_title("ACROSS dies: which die holds which layer\n"
                     "(die links 64 words/cycle -- platform input)",
                     fontsize=10)
        ax.grid(alpha=0.25, axis="y")

        # ---- (3) the same choices, in energy: flat, full scale
        ax = axes[2]
        es = [(base_E + sp) * 1e3 for sp in surplus]
        ax.bar(range(3), es, 0.6, color=[TEAL, SLATE, RED])
        for i, v in enumerate(es):
            ax.text(i, v + max(es) * 0.02, f"{v:.2f}", ha="center",
                    fontsize=10, fontweight="bold")
        spread = (max(es) - min(es)) / min(es) * 100
        ax.text(1, max(es) * 1.14, f"spread: +{spread:.2f}% -- energy does "
                "not care", ha="center", fontsize=10, color="0.35",
                fontweight="bold")
        ax.set_ylim(0, max(es) * 1.28)
        ax.set_xticks(range(3))
        ax.set_xticklabels([n for n, _, _ in ASG], fontsize=9)
        ax.set_ylabel("one prefill request, whole stack (mJ)")
        ax.set_title("the SAME choices, priced in energy\n"
                     "(full scale, no axis zoom)", fontsize=10)
        ax.grid(alpha=0.25, axis="y")

        fig.suptitle(f"Where placement bites -- {world}", fontsize=13)
        fig.tight_layout(rect=[0, 0, 1, 0.91])
        path = os.path.join(OUT, f"placement_impact_{key}.png")
        fig.savefig(path, dpi=130); plt.close(fig)
        print(f"PNG -> {path}")


if __name__ == "__main__":
    main()
