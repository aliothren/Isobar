"""Scenario B (attention offloaded) versions of the contention results.

Everything so far (contention_system, d2d_impact) is scenario A: attention on
chip, K/V write included. Offloading attention changes the two shields that
kept the network invisible:

  * prefill: the pipeline stage SHRINKS (feasible 48-die config, two dies
    per layer: the slower half-layer drops 23.49 -> 10.38 ms when qk^t/av and
    the K/V write leave the attention die), so there is less compute to hide
    transfers behind -- every knee moves UP (2x).
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
import dataclasses
import json
import os
import sys

sys.path.insert(0, "/home/workspace")

OUT = "/home/workspace/analysis"
from scripts import anchors as an
from scripts import fabric as _fabric_mod
# O26: the hand-rolled beat formulas below carry the same schedule_slack that
# link_occupancy applies (the 48-die package fabric's value, 1.0 = the bound)
SLACK = _fabric_mod.from_yaml("/home/workspace/models/fabric/mlx300_multidie48.yaml").schedule_slack
from scripts import figstyle as fs
from scripts import llm_workload as lw
STAYS = lw.stays_on_chip_under_offload     # scenario B: what remains on chip
N_LAYERS = 24
WORDS = 512 * 1024                      # one boundary, prefill (S x d_model)
WORDS_DEC = 1024                        # decode boundary (d_model)
CYC = an.CYCLE_S

BWS = [64.0, 256.0, 1024.0]


def unit_view(sysd):
    """O9: the external attention unit's per-layer costs (prefill/decode) and
    the die-chain busiest-wire integers WITH the offload streams on the die
    links (Q + K/V out to the attach point, attention output back). The unit
    sits at the die scheme's hub; the attention dies are units 0, 2, 4, ...
    of the 48-chain."""
    from scripts import fabric as fabric_mod, placement as pm
    import scripts.crossbar_comm as cc
    from scripts.analyze_d2d import assignments, with_link, UNITS, MULTI
    base = fabric_mod.from_yaml(MULTI)
    unit = base.attention_unit
    cfg = lw.GptConfig()
    ucfg = lw.GptConfig(n_layers=UNITS, name="units48")
    fm = with_link(base, "mesh", {"routing": "xy", "hub": "center"}, 256.0)
    pl = pm.sequential_fill(fm)
    # link energy priced at the mean hop count from the attention dies to the
    # attach point under the snake seating -- single source for every script
    hops = lw.unit_link_hops(fm, "snake")
    costs = {}
    for phase in ("prefill", "decode"):
        costs[phase] = lw.attention_unit_cost(cfg, 512, phase, unit, hops=hops)
        costs[phase]["mean_hops"] = hops
    words = 512 * cfg.d_model
    busiest = []
    for label, asg in assignments(fm):
        d = lw.die_to_die_activation(ucfg, 512, "prefill", fabric=fm, assignment=asg)
        adies = lw.attention_dies_of_chain(cfg.n_layers, asg)
        flows = d["flows"] + lw.offload_flows(cfg, 512, "prefill", adies)
        occ = cc.link_occupancy(flows, fm, CYC, pl)
        busiest.append((label, occ["bottleneck"]["volume"] / words))
    busiest.append(("bus (shared interposer)",
                    UNITS - 1 + 4 * cfg.n_layers * 1.0))   # 47 hand-offs + 4 stream-words per layer per boundary-word
    return {"unit": dataclasses.asdict(unit), "costs": costs, "busiest_with_streams": busiest}


def d2d_busiest():
    """Busiest-wire integers per D2D assignment on the FEASIBLE 48-unit
    chain (6x8 package, two dies per layer), computed through the same
    functions as analyze_d2d.py -- never hard-coded (a stale 24-die copy
    lived here once). Full-duplex mesh since O22: snake 1, sequential rows
    1, far pairs 4; the shared bus carries all 47. Pinned in
    test_feasible48.py."""
    from scripts import fabric as fabric_mod, placement as pm
    from scripts import llm_workload as lw
    import scripts.crossbar_comm as cc
    from scripts.analyze_d2d import assignments, with_link, UNITS, MULTI
    base = fabric_mod.from_yaml(MULTI)
    ucfg = lw.GptConfig(n_layers=UNITS, name="units48")
    fm = with_link(base, "mesh", {"routing": "xy", "hub": "center"}, 256.0)
    pl = pm.sequential_fill(fm)
    words = 512 * ucfg.d_model
    out = []
    for label, asg in assignments(fm):
        d = lw.die_to_die_activation(ucfg, 512, "prefill", fabric=fm,
                                     assignment=asg)
        occ = cc.link_occupancy(d["flows"], fm, CYC, pl)
        out.append((label, int(round(occ["bottleneck"]["volume"] / words))))
    out.append(("bus (shared interposer)", UNITS - 1))
    return out
ATTN_OPS = ("qkv_proj", "qk^t", "av", "out_proj")
FFN_OPS = ("ffn1", "ffn2")


def half_stages(per_op):
    """Per-die pipeline stages (two dies per layer): delegated to the single
    source llm_workload.half_layer_stages (O18/O24)."""
    return lw.half_layer_stages(per_op)


def stack_B(per_op, overlap="max"):
    """Scenario-B stack: static ops only, write gone with the attention.

    overlap="max": perfect compute/network overlap (headline end);
    overlap="sum": zero overlap -- the O7 bracket's other end."""
    if overlap == "max":
        return N_LAYERS * sum(max(o["compute_s"], o["serial_s"])
                              for o in per_op if STAYS(o["name"]))
    return N_LAYERS * sum(o["compute_s"] + o["serial_s"]
                          for o in per_op if STAYS(o["name"]))


def main():
    with open(os.path.join(OUT, "contention_system.json")) as f:
        sysd = json.load(f)

    out = {"note": "scenario B = attention offloaded, on-chip side only",
           "phases": {}}
    for phase, wds in (("prefill", WORDS), ("decode", WORDS_DEC)):
        d = sysd["phases"][phase]
        sf_B = N_LAYERS * sum(max(o["compute_s"], 0.0)
                              for o in next(iter(d["per_op"].values()))
                              if STAYS(o["name"]))
        print(f"=== {phase}, scenario B: stall-free stack "
              f"{sf_B*1e3:.3f} ms (A was {d['stall_free_s']*1e3:.2f} ms) ===")
        rows = {}
        for label, per_op in d["per_op"].items():
            tot = stack_B(per_op)
            tot_sum = stack_B(per_op, "sum")
            rows[label] = {"latency_s": tot, "mult": tot / sf_B,
                           "latency_sum_s": tot_sum, "mult_sum": tot_sum / sf_B}
            print(f"  {label:22} {tot*1e3:9.3f} ms   {tot/sf_B:5.2f}x"
                  f" ..{tot_sum/sf_B:5.2f}x"
                  f"   (A was {d['rows'][[r['label'] for r in d['rows']].index(label)]['mult']:.2f}x)")
        out["phases"][phase] = {"stall_free_B_s": sf_B, "on_die": rows}
        print()

    # ---------------- D2D pipelined, scenario B stage (48-die half-layers)
    per_star = next(iter(sysd["phases"]["prefill"]["per_op"].values()))
    stage_A, stage_B = half_stages(per_star)
    print(f"=== D2D pipelined, prefill: stage A {stage_A*1e3:.2f} ms -> "
          f"B {stage_B*1e3:.2f} ms (less compute to hide behind; "
          f"dividend +{(stage_A/stage_B-1)*100:.0f}%) ===")
    print(f"{'assignment':26}" + "".join(f"{f'@{b:,.0f} w/c':>14}" for b in BWS))
    d2d_out, d2d_out_sum = {}, {}
    D2D = d2d_busiest()
    for label, busiest in D2D:
        cells, cells_sum = [], []
        for bw in BWS:
            wirebeat = busiest * WORDS / bw * CYC * SLACK
            cells.append(max(stage_B, wirebeat) / stage_B)
            cells_sum.append((stage_B + wirebeat) / stage_B)
        d2d_out[label] = dict(zip((str(int(b)) for b in BWS), cells))
        d2d_out_sum[label] = dict(zip((str(int(b)) for b in BWS), cells_sum))
        print(f"  {label:24}" + "".join(
            f"  {c:>6.2f}..{cs:<5.2f}x" for c, cs in zip(cells, cells_sum)))

    # decode D2D under B: stage tiny, boundary tiny -- check anyway
    per_star_d = next(iter(sysd["phases"]["decode"]["per_op"].values()))
    _, stage_dB = half_stages(per_star_d)
    print(f"\n  decode stage B {stage_dB*1e6:.1f} us; sequential boundary beat at "
          f"64 w/c = {2*WORDS_DEC/64*CYC*1e6:.1f} us -> "
          f"{max(stage_dB, 2*WORDS_DEC/64*CYC)/stage_dB:.2f}x "
          "(decode is now touchable too)")
    out["d2d_prefill_B"] = {"stage_B_s": stage_B, "table": d2d_out,
                            "table_sum": d2d_out_sum}
    out["decode_stage_B_s"] = stage_dB

    # ---------------- O9: the external attention unit -- end-to-end scenario B
    uv = unit_view(sysd)
    cp, cd = uv["costs"]["prefill"], uv["costs"]["decode"]
    n_units = uv["unit"]["n_units"]
    unit_stage = cp["unit_s"] * N_LAYERS / n_units       # one unit serves N_LAYERS/n_units layers per beat
    stage_B_e2e = max(stage_B, unit_stage)
    print(f"\n=== O9: attention on the external unit ({uv['unit']['mac_per_second']/1e12:g} T MAC/s, "
          f"K/V {uv['unit']['kv_words_per_second']/1e9:g} GB/s, link "
          f"{an.gbps_of(uv['unit']['link_bandwidth_words_per_cycle']):.1f} GB/s, {n_units} unit(s)) ===")
    print(f"  prefill per layer: unit {cp['unit_s']*1e3:.3f} ms (compute {cp['compute_s']*1e3:.3f}, "
          f"K/V {cp['kv_s']*1e3:.3f}) + link {1e3*(cp['link_out_s']+cp['link_back_s']):.3f} ms "
          f"= chain {cp['chain_s']*1e3:.3f} ms; energy {cp['energy_J']*1e6:.1f} uJ "
          f"(compute {cp['compute_J']*1e6:.1f}, K/V {cp['kv_J']*1e6:.1f}, link {cp['link_J']*1e6:.1f})")
    print(f"  decode  per layer: chain {cd['chain_s']*1e3:.4f} ms (K/V read of the whole context "
          f"{cd['kv_s']*1e3:.4f} ms); energy {cd['energy_J']*1e6:.2f} uJ")
    e2e = {}
    for phase, c in (("prefill", cp), ("decode", cd)):
        d = sysd["phases"][phase]
        sf_B = out["phases"][phase]["stall_free_B_s"]
        sf_e2e = sf_B + N_LAYERS * c["chain_s"]
        rows = {}
        for label, v in out["phases"][phase]["on_die"].items():
            rows[label] = {"latency_s": v["latency_s"] + N_LAYERS * c["chain_s"],
                           "mult": (v["latency_s"] + N_LAYERS * c["chain_s"]) / sf_e2e}
        e2e[phase] = {"stall_free_e2e_s": sf_e2e, "unit_chain_s_x_layers": N_LAYERS * c["chain_s"],
                      "unit_energy_J_x_layers": N_LAYERS * c["energy_J"], "on_die": rows}
        print(f"  {phase}: die side {sf_B*1e3:.3f} ms -> end-to-end {sf_e2e*1e3:.3f} ms "
              f"(+{N_LAYERS*c['chain_s']*1e3:.2f} ms unit+link); unit energy +{N_LAYERS*c['energy_J']*1e3:.3f} mJ")
        print("   " + "  ".join(f"{lab.split(' ')[0]}/{lab.split(',')[-1].strip()[:6]} {r['mult']:.2f}x"
                                for lab, r in rows.items()))
    print(f"  pipelined: die stage B {stage_B*1e3:.2f} ms, unit stage {unit_stage*1e3:.2f} ms "
          f"-> beat {stage_B_e2e*1e3:.2f} ms; dividend die-side +{(stage_A/stage_B-1)*100:.0f}% "
          f"-> end-to-end +{(stage_A/stage_B_e2e-1)*100:.0f}%")
    print("  busiest die wire with the offload streams (boundary-words): " +
          ", ".join(f"{lab.split(' ')[0]} {b:.1f}" for lab, b in uv["busiest_with_streams"]))
    # pipelined beat with the streams on the die wires, at the example bandwidths
    anchor_bw = uv["unit"]["link_bandwidth_words_per_cycle"]        # GRS-class die links (the digital D2D anchor)
    bws = list(BWS) + [anchor_bw]
    print(f"  {'pipelined beat / die stage B, end-to-end':26}" + "".join(
        f"{f'@{b:,.0f} w/c':>14}" for b in BWS) + f"{'@' + an.by_key('grs').label + ' GB/s':>18}")
    beats = {}
    for lab, bz in uv["busiest_with_streams"]:
        cells = [max(stage_B_e2e, bz * WORDS / bw * CYC * SLACK) / stage_B for bw in bws]
        beats[lab] = dict(zip((str(int(b)) for b in bws), cells))
        print(f"  {lab:26}" + "".join(f"{c:>13.2f}x" for c in cells[:-1]) + f"{cells[-1]:>17.2f}x")
    # O25: the same beat read in the analog-reality D2D column (estimated band ends)
    aband = an.band(an.D2D).band
    analog_wc = [an.words_per_cycle(g) for g in aband]
    beats_analog = {}
    print(f"  {'-- analog-reality D2D band (est.)':26}" + "".join(f"{f'@{g:g} GB/s':>14}" for g in aband))
    for lab, bz in uv["busiest_with_streams"]:
        cells = [max(stage_B_e2e, bz * WORDS / bw * CYC * SLACK) / stage_B for bw in analog_wc]
        beats_analog[lab] = dict(zip((f"{g:g}" for g in aband), cells))
        print(f"  {lab:26}" + "".join(f"{c:>13.2f}x" for c in cells))

    out["offload_unit"] = {"unit": uv["unit"], "per_layer": uv["costs"],
                           "unit_stage_s": unit_stage, "beat_B_e2e_s": stage_B_e2e,
                           "dividend_die_side": stage_A / stage_B - 1,
                           "dividend_e2e": stage_A / stage_B_e2e - 1,
                           "busiest_with_streams": uv["busiest_with_streams"],
                           "beat_with_streams": beats,
                           "anchor_bw_words_per_cycle": anchor_bw,
                           "anchor_label": an.by_key("grs").label,
                           "beat_with_streams_analog_gbps": beats_analog,
                           "e2e": e2e}

    with open(os.path.join(OUT, "offload_contention.json"), "w") as f:
        out["fabric"] = sysd.get("fabric")
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
    fs.annotate_bar_ties(ax, x - 0.19, [v * 1e3 for v in on], dy=0.03, text="identical: network hidden at 16,384 w/c")
    fs.annotate_bar_ties(ax, x + 0.19, [v * 1e3 for v in off], dy=0.03, text="identical: network hidden at 16,384 w/c")
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
    worst_dec = max(v["mult"] for v in dec_B.values())
    ax.set_title("Decode: even with the write block removed,\n"
                 f"the on-die network stays at {worst_dec:.1f}x",
                 fontsize=10)
    ax.legend(fontsize=8); ax.grid(alpha=0.25, axis="y")

    # ---- (3) pipelined throughput at 64 w/c
    ax = axes[2]
    CYC, WORDS = an.CYCLE_S, 512 * 1024
    # FEASIBLE 48-die configuration (two dies per layer): stage = the slower
    # half-layer; busiest-wire integers from the 6x8 chain (snake 1,
    # sequential 2, far pairs 8, bus 47). Read at a LOW example input
    # (64 w/c ~ 0.044 GB/s) -- measured D2D links sit two orders higher, so
    # this panel illustrates the mechanism, not an expected operating point.
    stage_A, stage_B = half_stages(pre_A["per_op"]["mesh, glb centre"])
    stage_B = max(stage_B, out.get("offload_unit", {}).get("unit_stage_s", 0.0))   # O9: unit is a stage too
    labels3 = ["ideal\nnetwork", "snake", "sequential", "far pairs\n(worst)",
               "bus"]
    busiest = [0] + [b for _, b in d2d_busiest()]
    def thr(stage, b):
        net = b * WORDS / 64.0 * CYC * SLACK
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
    ax.set_title(f"The offload dividend (+{(stage_A/stage_B-1)*100:.0f}%, end-to-end "
                 "with the external unit)\nis paid out only where the package "
                 "network is not the bottleneck", fontsize=10)
    ax.legend(fontsize=8, loc="center right"); ax.grid(alpha=0.25, axis="y")

    fig.suptitle("What offloading attention changes, per condition", fontsize=12)
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

    CYC, WORDS = an.CYCLE_S, 512 * 1024
    # feasible 48-die configuration: same chain, fabric and assignments as
    # analyze_d2d (imported -- single source for the constructions)
    from scripts.analyze_d2d import assignments as d2d_assignments, UNITS
    fabM = fabric_mod.from_yaml(
        "/home/workspace/models/fabric/mlx300_multidie48.yaml")
    ucfg = lw.GptConfig(n_layers=UNITS, name="units48")
    named = dict((lbl, asg) for lbl, asg in d2d_assignments(fabM))
    bus_int = dict(d2d_busiest())
    ASG = [("snake", named["snake"], bus_int["snake"]),
           ("sequential\nrows", named["sequential rows"],
            bus_int["sequential rows"]),
           ("far pairs\n(worst)", named["far pairs (adversarial)"],
            bus_int["far pairs (adversarial)"])]
    surplus = [lw.die_to_die_activation(ucfg, 512, "prefill", fabric=fabM,
                                        assignment=a)["energy_J"]
               for _, a, _ in ASG]

    with open(os.path.join(OUT, "gpt2_system_totals_prefill.json")) as f:
        totals = json.load(f)["scenarios"]

    pre_A = {r["label"]: r["latency_s"] for r in sysd["phases"]["prefill"]["rows"]}
    dec_A = {r["label"]: r["latency_s"] for r in sysd["phases"]["decode"]["rows"]}
    pre_B = {k: v["latency_s"] for k, v in out["phases"]["prefill"]["on_die"].items()}
    dec_B = {k: v["latency_s"] for k, v in out["phases"]["decode"]["on_die"].items()}
    stage_A, stage_B = half_stages(
        sysd["phases"]["prefill"]["per_op"]["mesh, glb centre"])
    stage_B = max(stage_B, out.get("offload_unit", {}).get("unit_stage_s", 0.0))   # O9

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
        ax.text(1, max(es) * 1.14, f"spread: +{spread:.2f}% over THESE three "
                "chain-like seatings", ha="center", fontsize=10, color="0.35",
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
