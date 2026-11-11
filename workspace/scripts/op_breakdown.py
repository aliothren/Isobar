"""Per-operator cost ledger: ONE entry point, every cost item listed on its own.

For every operator of the simulated model (one transformer block per phase;
the blocks are structurally identical, so each row is also given x n_layers)
this script reports the operator's LATENCY and ENERGY and their breakdown.
Nothing is merged into coarse categories: every CiMLoop component, every
overlay term and every analytic term is its own row, with a group label
only as an annotation. Items the platform does NOT model are listed too,
with the value replaced by the marker "not modelled, not counted" -- they are never
silently absent.

Conventions (stated on every output):
  * basis: co-residency shares of the feasible 48-die seating (the published
    355M basis) unless --no-shares;
  * wire accounting: full-duplex direction-split links (bus shared) and
    16-bit partial sums up the tree (O22/O23);
  * the network term is given three ways: occupancy of the busiest wire,
    the part EXPOSED on the critical path under perfect compute/network
    overlap (the headline end), and under zero overlap (O7 bracket);
  * bandwidth and scheme are platform inputs: pick them on the command line.

Outputs (under --out, default analysis/op_breakdown/):
  op_breakdown.json                 everything, machine-readable
  op_breakdown_types_<phase>.csv    whole-model view: one row per operator TYPE, under
                                    both conditions (attention on chip / offloaded)
  op_breakdown_<phase>.csv          long format: op, kind, group, item, value, unit, note
  op_breakdown.md                   the tables (operator-type shares, per-op totals x
                                    n_layers, then every item)
  op_breakdown_energy_<phase>.png   stacked bars, one bar per op, one segment per item
  op_breakdown_latency_<phase>.png  same for latency (occupancy view + exposed view)

Usage (container, sequential, one mapper run per op):
    python3 scripts/op_breakdown.py [--S 512] [--bw 16384]
        [--scheme star|mesh_centre|mesh_corner|htree|bus] [--no-shares]
        [--phases prefill,decode] [--out analysis/op_breakdown]
    CIMSIM_FABRIC=models/fabric/mlx300_multidie48.yaml selects the package
    (die-to-die rows are zero on the shipped single-die config, and say so).
"""
import argparse
import csv
import dataclasses
import json
import os
import sys

sys.path.insert(0, "/home/workspace")

UNMODELED = "not modelled, not counted"
OFFLOADED = "offloaded to the off-chip unit (see the \"attention on the off-chip unit\" row)"
from scripts import fabric as _fabric_mod   # noqa: E402
CYC_DEFAULT = _fabric_mod.default().device.cycle_seconds   # O17a: the fabric's device, not a literal
ATTN_OPS = ("qk^t", "av")                 # leave the chip under offload (with their K/V write)
CONDITIONS = {"on_chip": "attention on chip", "offloaded": "attention offloaded (end to end: on chip + off-chip unit)"}
# the model's operator TYPES the platform does not simulate (whole-model view)
MODEL_UNMODELED_TYPES = []          # O24 filled the non-matmul rows (C19)
TYPE_LABEL = {"attention_unit": "attention on the off-chip unit (QKᵀ + softmax + AV, K/V in the unit memory)",
              "qkv_proj": "Q/K/V projection (qkv_proj)", "qk^t": "attention scores QKᵀ (qk^t, with K write)",
              "av": "attention weighting AV (av, with V write)", "out_proj": "output projection (out_proj)",
              "ffn1": "FFN first layer (ffn1)", "ffn2": "FFN second layer (ffn2)",
              "softmax": "softmax (digital unit)", "gelu": "GELU (FFN activation, digital unit)",
              "layernorm": "LayerNorm ×2 (digital unit)", "residual": "residual add ×2 (digital unit)",
              "embedding": "embedding lookup (off-chip read, once per model)",
              "lm_head": "LM head (matmul, last token, once per model)"}
PER_MODEL_OPS = ("embedding", "lm_head")      # counted once, not x n_layers

# component -> group annotation (annotation ONLY; rows are never merged)
GROUP = {
    "cim_unit": "analog compute", "integrator": "analog compute", "wordline_cap": "analog compute",
    "wordline_drivers": "analog compute", "row_drivers": "analog compute",
    "column_drivers": "analog compute", "weight_drivers": "analog compute",
    "virtual_bitwise_mac": "analog compute", "inter_1bit_x_1bit_mac_spatial": "analog compute",
    "inter_row_spatial": "analog compute", "inter_column_spatial": "analog compute",
    "adc": "conversion", "sample": "conversion", "shift_add": "conversion",
    "glb": "buffer", "input_buffer": "buffer", "output_buffer": "buffer",
    "chip2chip_data_staging": "buffer",
    "router": "on-die network", "inter_macro_in_die_spatial": "on-die network",
    "inter_core_in_macro_spatial": "on-die network",
    "inter_crossbar_in_core_spatial": "on-die network",
    "chip2chip_link": "off-chip port", "here_to_fix_a_bug": "other",
}
# links that carry NO energy model in the calibrated die (FIXLIST O1)
UNPRICED = {"inter_core_in_macro_spatial", "inter_crossbar_in_core_spatial",
            "inter_macro_in_die_spatial", "inter_row_spatial",
            "inter_column_spatial", "inter_1bit_x_1bit_mac_spatial"}

SCHEMES = {
    "star": ("star", {}),
    "mesh_centre": ("mesh", {"routing": "xy", "hub": "center"}),
    "mesh_corner": ("mesh", {"routing": "xy", "hub": "corner"}),
    "htree": ("h_tree", {"branching": 4}),
    "bus": ("bus", {"driver": "center"}),
}

ENERGY_UNMODELED = [
    ("internal structure of the off-chip unit (buffers, control, quantisation)", "priced through its black-box interface: rate, mean overhead, K/V memory, link"),
    ("distance energy of the core/crossbar links", "the component exists but has no energy model (input not provided); its rows below are 0"),
    ("cross-die sharding of a long-context K/V beyond capacity (>~8k tokens)", "FIXLIST O14"),
]
LATENCY_UNMODELED = [
    ("network queueing (load vectors with equal peaks are not distinguished)", "only the busiest wire's occupancy is taken; the overlap bracket gives both ends"),
    ("compute / memory overlap inside the off-chip unit", "assumes the unit's compute and K/V access are serial"),
    ("pipeline bubbles / imbalance", "the pipeline view assumes perfect microbatch pipelining"),
]


# --------------------------------------------------------------------- ledger
def energy_items(levels, overlay_rows, cimloop_J, write_J=0.0, rewrite_J=0.0,
                 d2d_surplus_J=0.0, d2d_note=""):
    """Every energy item of one op, each on its own row. `cimloop_J` is the
    position-blind CiMLoop total; the placement re-pricing rows are an
    ADDITIONAL charge beyond it (scenario-A accounting: raw + overlay +
    write). Returns (items, residual_J) with
    sum(numeric items) == cimloop_J + overlay + write_J + rewrite_J +
    d2d_surplus_J and residual == cimloop_J - sum(component rows), reported
    as its own row (CiMLoop energy lines its component sections do not
    carry)."""
    items = []
    comp_sum = 0.0
    for name in sorted(levels):
        e = levels[name]["energy_J"]
        comp_sum += e
        note = ""
        if name in UNPRICED and e == 0.0:
            note = "no energy model (not priced)"
        items.append({"group": GROUP.get(name, "other"), "item": f"component {name}",
                      "en": name, "value": e, "unit": "J", "note": note})
    # placement re-pricing beyond the flat CiMLoop charge, per component
    ov_sum = 0.0
    for name, fanout, base, hops_ratio, pa in overlay_rows:
        delta = pa - base
        ov_sum += delta
        items.append({"group": GROUP.get(name, "on-die network"),
                      "item": f"placement distance repricing increment {name}",
                      "en": f"placement re-pricing {name}",
                      "value": delta, "unit": "J",
                      "note": f"mean hops / reference hops = {hops_ratio:.3f}"})
    items.append({"group": "write", "item": "K/V write programming energy", "en": "K/V write",
                  "value": write_J, "unit": "J",
                  "note": "" if write_J else "static operators do not write"})
    items.append({"group": "write", "item": "weight rewrite energy (temporal rewrite policy)",
                  "en": "weight rewrite", "value": rewrite_J, "unit": "J",
                  "note": "" if rewrite_J else "no rewrite in this configuration"})
    items.append({"group": "D2D", "item": "die-to-die hand-off surplus energy (hops beyond the flat charge)",
                  "en": "D2D hand-off surplus", "value": d2d_surplus_J,
                  "unit": "J", "note": d2d_note})
    residual = cimloop_J - comp_sum
    items.append({"group": "other", "item": "unattributed residual (CiMLoop total − sum of the component rows)",
                  "en": "unlisted residual", "value": residual, "unit": "J",
                  "note": "CiMLoop's operator total = the summary table's per-compute energy (finite precision) "
                          "× computes; its difference from the exact sum of the components' Energy (total) lines "
                          "is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention"})
    for name, why in ENERGY_UNMODELED:
        items.append({"group": "not modelled", "item": name, "en": name, "value": UNMODELED,
                      "unit": "", "note": why})
    return items, residual


def _slack():
    from scripts import fabric as _fm
    return _fm.default().schedule_slack


def latency_items(compute_s, write_s, serial_s, prop_s, d2d_s=0.0,
                  d2d_note=""):
    """Every latency item of one op. Exposed amounts follow the critical
    path write + max(compute, serial) + prop (perfect overlap) and
    write + compute + serial + prop (zero overlap)."""
    exposed_max = max(compute_s, serial_s) - compute_s
    tot_max = write_s + max(compute_s, serial_s) + prop_s
    tot_sum = write_s + compute_s + serial_s + prop_s
    items = [
        {"group": "compute", "item": "array compute (Timeloop cycles)", "en": "compute",
         "value": compute_s, "unit": "s", "note": ""},
        {"group": "write", "item": "K/V write (serial, before compute)", "en": "K/V write",
         "value": write_s, "unit": "s", "note": "" if write_s else "static operators do not write"},
        {"group": "on-die network", "item": "busiest-wire occupancy (serialization)",
         "en": "busiest-wire occupancy", "value": serial_s, "unit": "s",
         "note": "occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule "
                 f"slack (platform input schedule_slack, currently {_slack():g})"},
        {"group": "on-die network", "item": "network exposure (perfect-overlap end = max(compute, occupancy) − compute)",
         "en": "network exposed (perfect overlap)", "value": exposed_max,
         "unit": "s", "note": "the end reported by default"},
        {"group": "on-die network", "item": "network exposure (zero-overlap end = occupancy)",
         "en": "network exposed (zero overlap)", "value": serial_s, "unit": "s",
         "note": "upper end of the overlap bracket"},
        {"group": "propagation", "item": "distance propagation delay", "en": "propagation",
         "value": prop_s, "unit": "s", "note": ""},
        {"group": "D2D", "item": "die-to-die hand-off transfer (hidden state produced by this operator)",
         "en": "D2D hand-off (occupancy)", "value": d2d_s, "unit": "s",
         "note": d2d_note},
    ]
    for name, why in LATENCY_UNMODELED:
        items.append({"group": "not modelled", "item": name, "en": name, "value": UNMODELED,
                      "unit": "", "note": why})
    totals = {"perfect_overlap_s": tot_max, "zero_overlap_s": tot_sum}
    return items, totals


# ------------------------------------------------------------------ helpers
def _scheme_fabric(base, name, bw):
    from scripts.analyze_contention_system import variant
    topo, params = SCHEMES[name]
    return variant(base, topo, params, bw)


def _d2d_per_boundary(fab, cfg, S, phase):
    """Per-boundary hand-off transfer time and surplus energy on the chosen
    package (snake ordering), or zeros with a note."""
    from scripts import llm_workload as lw
    import scripts.crossbar_comm as cc
    from scripts import placement as pm
    try:
        die = fab.level("die")
    except KeyError:
        return 0.0, 0.0, "single-die configuration: no die-to-die hand-off"
    if die.per_parent <= 1:
        return 0.0, 0.0, "single-die configuration: no die-to-die hand-off"
    n = die.per_parent
    ucfg = lw.GptConfig(d_model=cfg.d_model, n_heads=cfg.n_heads, d_ff=cfg.d_ff,
                        n_layers=n, name=f"units{n}")
    mx, _ = die.mesh
    snake = []
    for L in range(n):
        row, col = divmod(L, mx)
        snake.append(row * mx + (mx - 1 - col if row % 2 else col))
    d = lw.die_to_die_activation(ucfg, S, phase, fabric=fab, assignment=snake)
    words = S * cfg.d_model if phase == "prefill" else cfg.d_model
    bw = die.link.bandwidth_words_per_cycle
    if not bw:
        return 0.0, d["energy_J"] / max(d["n_boundaries"], 1), \
            "die link without a bandwidth (shipped default): transfer time counted as 0"
    t = words / bw * CYC_DEFAULT
    return t, d["energy_J"] / max(d["n_boundaries"], 1), \
        f"snake seating, {n}-unit chain, die link {bw:,.0f} words/cycle; hidden behind the stack's compute in the single-pass view"


def ledger_for_elementwise(eo, cost, digital):
    """Ledger entry of one non-matmul operator (O24): energy = glb passes +
    digital arithmetic, latency = digital time (serial with the matmuls)."""
    e_items = [
        {"group": "buffer", "item": f"glb read/write ({eo.glb_passes} passes × {eo.elements:,} elements)",
         "en": "glb passes", "value": cost["glb_J"], "unit": "J",
         "note": f"glb {lw_glb_note()}"},
        {"group": "digital unit", "item": "digital-unit arithmetic (add / mul / lookup)", "en": "digital arithmetic",
         "value": cost["arith_J"], "unit": "J",
         "note": f"per element {eo.adds:g} adds + {eo.muls:g} muls + {eo.luts:g} lookups; {digital.calibration}"},
    ]
    for name, why in ENERGY_UNMODELED:
        e_items.append({"group": "not modelled", "item": name, "en": name, "value": UNMODELED,
                        "unit": "", "note": why})
    l_items = [
        {"group": "digital unit", "item": f"digital-unit compute ({eo.arith_ops:,.0f} operations ÷ {digital.lanes} lanes × {digital.clock_hz/1e9:g} GHz)",
         "en": "digital compute", "value": cost["latency_s"], "unit": "s",
         "note": "serial with the adjacent matmuls (stated assumption)"},
        {"group": "on-die network", "item": "busiest-wire occupancy (serialization)", "en": "busiest-wire occupancy",
         "value": 0.0, "unit": "s", "note": "the digital unit sits next to the glb and does not use the on-die network (assumption)"},
    ]
    for name, why in LATENCY_UNMODELED:
        l_items.append({"group": "not modelled", "item": name, "en": name, "value": UNMODELED,
                        "unit": "", "note": why})
    return {"op": eo.name, "kind": "elementwise",
            "shape": {"elements": eo.elements, "after": eo.after},
            "energy_total_J": cost["energy_J"], "energy_residual_J": 0.0,
            "energy_items": e_items,
            "latency_total_s": {"perfect_overlap_s": cost["latency_s"],
                                "zero_overlap_s": cost["latency_s"]},
            "latency_items": l_items, "network_bound": False, "bottleneck_wire": None}


def ledger_for_attention_unit(cost, unit):
    """Ledger entry of the offloaded attention on the external unit (O9),
    per layer: link streams, unit compute, K/V memory, per-call overhead."""
    e_items = [
        {"group": "off-chip unit", "item": f"unit compute ({cost['macs']:,} MACs + softmax {cost['softmax_ops']:,} operations) × {unit.pj_per_mac:g} pJ",
         "en": "unit compute", "value": cost["compute_J"], "unit": "J", "note": unit.calibration},
        {"group": "off-chip unit", "item": f"K/V memory read/write ({cost['kv_write_words']:,} writes + {cost['kv_read_words']:,} reads)",
         "en": "unit K/V memory", "value": cost["kv_J"], "unit": "J", "note": ""},
        {"group": "link", "item": "die↔unit link (Q out, K/V out, attention output back)",
         "en": "die-unit link", "value": cost["link_J"], "unit": "J",
         "note": f"priced over the mean {cost['link_hops']:g} hops from the dies to the attach point (these words are not in the CiMLoop account)"},
    ]
    l_items = [
        {"group": "link", "item": "Q + K/V out (die → unit)", "en": "link out",
         "value": cost["link_out_s"], "unit": "s", "note": ""},
        {"group": "off-chip unit", "item": "unit compute (including the fixed per-call overhead)", "en": "unit compute",
         "value": cost["compute_s"], "unit": "s", "note": ""},
        {"group": "off-chip unit", "item": "K/V memory read/write (reads the whole stored context)", "en": "unit K/V memory",
         "value": cost["kv_s"], "unit": "s", "note": "serial with compute (assumption)"},
        {"group": "link", "item": "attention output back (unit → die)", "en": "link back",
         "value": cost["link_back_s"], "unit": "s", "note": ""},
    ]
    for name, why in LATENCY_UNMODELED:
        l_items.append({"group": "not modelled", "item": name, "en": name, "value": UNMODELED,
                        "unit": "", "note": why})
    return {"op": "attention_unit", "kind": "offloaded_unit",
            "shape": {"macs": cost["macs"], "kv_read_words": cost["kv_read_words"]},
            "energy_total_J": cost["energy_J"], "energy_residual_J": 0.0,
            "energy_items": e_items,
            "latency_total_s": {"perfect_overlap_s": cost["chain_s"],
                                "zero_overlap_s": cost["chain_s"]},
            "latency_items": l_items, "network_bound": False, "bottleneck_wire": None,
            "offload_only": True}


def ledger_for_embedding(emb):
    lat = emb["latency_s"]
    e_items = [{"group": "off-chip", "item": f"off-chip read of {emb['words']:,} words × DRAM energy per word",
                "en": "off-chip read", "value": emb["energy_J"], "unit": "J", "note": ""}]
    l_items = [{"group": "off-chip", "item": "off-chip read transfer", "en": "off-chip read",
                "value": lat if lat is not None else 0.0, "unit": "s",
                "note": "" if emb["timed"] else "off-chip port bandwidth not set (fabric.offchip_bandwidth_words_per_cycle): priced, not timed"}]
    return {"op": "embedding", "kind": "offchip_read", "shape": {"words": emb["words"]},
            "energy_total_J": emb["energy_J"], "energy_residual_J": 0.0,
            "energy_items": e_items,
            "latency_total_s": {"perfect_overlap_s": lat or 0.0, "zero_overlap_s": lat or 0.0},
            "latency_items": l_items, "network_bound": False, "bottleneck_wire": None}


def ledger_marker(name, kind, why):
    """An operator the current run cannot price: a row with the reason, never
    a silent omission. Totals treat it as zero and the type table shows the
    marker."""
    return {"op": name, "kind": kind, "shape": {}, "energy_total_J": 0.0,
            "energy_residual_J": 0.0,
            "energy_items": [{"group": "not counted", "item": why, "en": "not counted",
                              "value": UNMODELED, "unit": "", "note": why}],
            "latency_total_s": {"perfect_overlap_s": 0.0, "zero_overlap_s": 0.0},
            "latency_items": [{"group": "not counted", "item": why, "en": "not counted",
                               "value": UNMODELED, "unit": "", "note": why}],
            "network_bound": False, "bottleneck_wire": None, "marker": why}


def lw_glb_note():
    return "access energy per word from the CiMLoop calibration of the same die (ffn1 run: 15.47 pJ/word)"


def ledger_for_op(r, phase, fab_scheme, cyc, d2d):
    from scripts import crossbar_comm as cc
    from scripts import placement as pm
    op = r["op"]
    flows, _, _, _ = cc.build_flows(r["output_dir"], verbose=False)
    occ = cc.link_occupancy(flows, fab_scheme, cyc, pm.sequential_fill(fab_scheme))
    serial = occ["serialization_s"]
    rewrite_J = r["rewrite"]["energy_J"] if r.get("rewrite") else 0.0
    t_d2d, e_d2d, note = d2d
    ends_unit = op.name in ("out_proj", "ffn2")     # the two-dies-per-layer seating
    d2d_note = note if ends_unit else "not at a unit boundary (the hand-off belongs to out_proj / ffn2)"
    e_items, resid = energy_items(r["levels"], r["analysis"]["rows"],
                                  r["compute_J"], r["write_J"], rewrite_J,
                                  e_d2d if ends_unit else 0.0, d2d_note)
    overlay = sum(pa - base for _, _, base, _, pa in r["analysis"]["rows"])
    l_items, tot = latency_items(r["compute_latency_s"], r["write_latency_s"],
                                 serial, r["dist_latency_s"],
                                 t_d2d if ends_unit else 0.0, d2d_note)
    total_E = (r["compute_J"] + overlay + r["write_J"] + rewrite_J
               + (e_d2d if ends_unit else 0.0))
    return {"op": op.name, "kind": op.kind,
            "shape": {"P": op.P, "C": op.C, "M": op.M, "N": op.N},
            "energy_total_J": total_E, "energy_residual_J": resid,
            "energy_items": e_items,
            "latency_total_s": tot, "latency_items": l_items,
            "network_bound": serial > r["compute_latency_s"],
            "bottleneck_wire": (occ["bottleneck"] or {}).get("resource")}


def type_table(ops, n_layers, condition):
    """Whole-model view: one row per operator TYPE (x n_layers), shares over
    the counted total; under 'offloaded' the attention ops are rows carrying
    the OFFLOADED marker; the operator types the platform does not simulate
    are rows carrying the UNMODELED marker. Never merged, never absent."""
    from scripts import llm_workload as lw
    leaves = lambda name: condition == "offloaded" and not lw.stays_on_chip_under_offload(name)
    mult = lambda o: 1 if o["op"] in PER_MODEL_OPS else n_layers
    ops = [o for o in ops if not (o.get("offload_only") and condition == "on_chip")]
    counted = [o for o in ops if not leaves(o["op"])]
    E = sum(o["energy_total_J"] * mult(o) for o in counted)
    L1 = sum(o["latency_total_s"]["perfect_overlap_s"] * mult(o) for o in counted)
    L2 = sum(o["latency_total_s"]["zero_overlap_s"] * mult(o) for o in counted)
    rows = []
    for o in ops:
        if o.get("marker"):
            rows.append({"type": TYPE_LABEL.get(o["op"], o["op"]), "op": o["op"],
                         "energy_J": o["marker"], "energy_share": "",
                         "latency_s": o["marker"], "latency_share": "",
                         "latency_zero_overlap_s": o["marker"], "note": o["marker"]})
            continue
        if leaves(o["op"]):
            rows.append({"type": TYPE_LABEL.get(o["op"], o["op"]), "op": o["op"],
                         "energy_J": OFFLOADED, "energy_share": "",
                         "latency_s": OFFLOADED, "latency_share": "",
                         "latency_zero_overlap_s": OFFLOADED, "note": ""})
            continue
        e = o["energy_total_J"] * mult(o)
        l1 = o["latency_total_s"]["perfect_overlap_s"] * mult(o)
        l2 = o["latency_total_s"]["zero_overlap_s"] * mult(o)
        note = ""
        if o["op"] == "embedding" and not o["latency_items"][0].get("note", "") == "":
            note = o["latency_items"][0]["note"]
        rows.append({"type": TYPE_LABEL.get(o["op"], o["op"]), "op": o["op"],
                     "energy_J": e, "energy_share": e / E if E else 0.0,
                     "latency_s": l1, "latency_share": l1 / L1 if L1 else 0.0,
                     "latency_zero_overlap_s": l2, "note": note})
    rows.append({"type": "counted total (matmuls + digital-unit operators + off-chip reads)", "op": "", "energy_J": E,
                 "energy_share": 1.0, "latency_s": L1, "latency_share": 1.0,
                 "latency_zero_overlap_s": L2, "note": "denominator of the shares"})
    for name, why in MODEL_UNMODELED_TYPES:
        rows.append({"type": name, "op": "", "energy_J": UNMODELED, "energy_share": "",
                     "latency_s": UNMODELED, "latency_share": "",
                     "latency_zero_overlap_s": UNMODELED, "note": why})
    return {"condition": CONDITIONS[condition], "rows": rows,
            "totals": {"energy_J": E, "latency_perfect_overlap_s": L1,
                       "latency_zero_overlap_s": L2}}


# -------------------------------------------------------------------- output
def _num(v, unit):
    if v == UNMODELED:
        return v
    if unit == "J":
        return f"{v*1e6:,.2f} µJ"
    if unit == "s":
        return f"{v*1e3:,.4f} ms"
    return str(v)


def write_outputs(result, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "op_breakdown.json"), "w") as f:
        from scripts import fabric as _fm
        result["fabric"] = _fm.provenance(_fm.default())
        json.dump(result, f, indent=1, ensure_ascii=False)
    md = ["# Per-operator cost ledger", "",
          f"Model {result['model']}, S = {result['S']}, {result['n_layers']} layers; "
          f"basis: {result['basis']}; wiring scheme {result['scheme']}, link bandwidth "
          f"{result['bw_words_per_cycle']:,.0f} words/cycle (platform input); accounting: {result['wire_accounting']}; "
          f"busiest-wire occupancy = the lower bound of any schedule for the given routing × the schedule slack {result.get('schedule_slack', 1.0):g}.",
          "One row per item, nothing merged; items marked **" + UNMODELED + "** are not modelled by the platform.", ""]
    for phase, ph in result["phases"].items():
        n = result["n_layers"]
        md += [f"## {phase}", ""]
        for cond, tt in ph["type_tables"].items():
            md += [f"### Operator types, whole-model shares -- {tt['condition']}", "",
                   "| operator type | whole-model energy (mJ) | energy share | whole-model latency (ms, perfect overlap) | latency share | whole-model latency (ms, zero overlap) | note |",
                   "|---|---|---|---|---|---|---|"]
            for r in tt["rows"]:
                if isinstance(r["energy_J"], str):
                    md.append(f"| {r['type']} | {r['energy_J']} | | {r['latency_s']} | | | {r['note']} |")
                else:
                    md.append(f"| {r['type']} | {r['energy_J']*1e3:,.3f} | {r['energy_share']:.1%} | "
                              f"{r['latency_s']*1e3:,.2f} | {r['latency_share']:.1%} | "
                              f"{r['latency_zero_overlap_s']*1e3:,.2f} | {r['note']} |")
            md.append("")
        md += ["### Per-operator totals (one layer / × layers; the per-operator data do not depend on the condition)", "",
               "| operator | kind | total energy (µJ) | whole-model energy (mJ) | latency, perfect overlap (ms) | latency, zero overlap (ms) | whole-model latency, perfect overlap (ms) | network-bound |",
               "|---|---|---|---|---|---|---|---|"]
        for o in ph["ops"]:
            md.append(f"| {o['op']} | {o['kind']} | {o['energy_total_J']*1e6:,.2f} | "
                      f"{o['energy_total_J']*n*1e3:,.3f} | "
                      f"{o['latency_total_s']['perfect_overlap_s']*1e3:,.4f} | "
                      f"{o['latency_total_s']['zero_overlap_s']*1e3:,.4f} | "
                      f"{o['latency_total_s']['perfect_overlap_s']*n*1e3:,.2f} | "
                      f"{'yes' if o['network_bound'] else 'no'} |")
        E = sum(o["energy_total_J"] for o in ph["ops"]) * n
        L1 = sum(o["latency_total_s"]["perfect_overlap_s"] for o in ph["ops"]) * n
        L2 = sum(o["latency_total_s"]["zero_overlap_s"] for o in ph["ops"]) * n
        md += ["", f"Whole-model total: energy {E*1e3:,.3f} mJ; latency {L1*1e3:,.2f} ms (perfect overlap)"
               f" / {L2*1e3:,.2f} ms (zero overlap).", ""]
        for o in ph["ops"]:
            shape = ",".join(f"{k}={v:,}" if isinstance(v, int) else f"{k}={v}"
                             for k, v in o["shape"].items())
            md += [f"### {phase} · {o['op']}({o['kind']}{',' + shape if shape else ''})", "",
                   "Energy:", "", "| group | item | value | share of the operator's energy | note |", "|---|---|---|---|---|"]
            for it in o["energy_items"]:
                share = "" if it["value"] == UNMODELED or o["energy_total_J"] == 0 \
                    else f"{it['value']/o['energy_total_J']:.2%}"
                md.append(f"| {it['group']} | {it['item']} | {_num(it['value'], it['unit'])} | {share} | {it['note']} |")
            md += ["", "Latency:", "", "| group | item | value | note |", "|---|---|---|---|"]
            for it in o["latency_items"]:
                md.append(f"| {it['group']} | {it['item']} | {_num(it['value'], it['unit'])} | {it['note']} |")
            md.append("")
        with open(os.path.join(out_dir, f"op_breakdown_types_{phase}.csv"), "w",
                  newline="") as f:
            w = csv.writer(f)
            w.writerow(["condition", "type", "op", "energy_J", "energy_share",
                        "latency_perfect_overlap_s", "latency_share",
                        "latency_zero_overlap_s", "note"])
            for cond, tt in ph["type_tables"].items():
                for r in tt["rows"]:
                    w.writerow([tt["condition"], r["type"], r["op"], r["energy_J"],
                                r["energy_share"], r["latency_s"], r["latency_share"],
                                r["latency_zero_overlap_s"], r["note"]])
        with open(os.path.join(out_dir, f"op_breakdown_{phase}.csv"), "w",
                  newline="") as f:
            w = csv.writer(f)
            w.writerow(["op", "kind", "axis", "group", "item", "value", "unit", "note"])
            for o in ph["ops"]:
                for axis, key in (("energy", "energy_items"), ("latency", "latency_items")):
                    for it in o[key]:
                        w.writerow([o["op"], o["kind"], axis, it["group"], it["item"],
                                    it["value"], it["unit"], it["note"]])
    with open(os.path.join(out_dir, "op_breakdown.md"), "w") as f:
        f.write("\n".join(md))
    make_figures(result, out_dir)


def make_figures(result, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    for phase, ph in result["phases"].items():
        ops = ph["ops"]
        names = [o["op"] for o in ops]
        # ---- operator-type shares of the whole model, both conditions
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
        for ax, (key, title) in zip(axes, (("energy_share", "energy share"),
                                           ("latency_share", "latency share (perfect-overlap end)"))):
            conds = list(ph["type_tables"].items())
            left = np.zeros(len(conds))
            cmap = plt.cm.tab10(np.linspace(0, 1, len(ops)))
            for o, c in zip(ops, cmap):
                vals = np.array([next((r[key] for r in tt["rows"] if r["op"] == o["op"]
                                       and not isinstance(r[key], str)), 0.0)
                                 for _, tt in conds]) * 100
                ax.barh([{"on_chip": "attention on chip",
                          "offloaded": "attention offloaded"}[k] for k, _ in conds],
                        vals, left=left, color=c, label=o["op"])
                left += vals
            ax.set_xlim(0, 100); ax.set_xlabel(f"{title} of the counted matmuls (%)")
            ax.set_title(f"{phase}: operator-type {title}\n(non-matmul operators: "
                         "not modeled, not counted)", fontsize=9.5)
            ax.grid(alpha=0.25, axis="x")
        axes[0].legend(fontsize=8, ncol=3, loc="lower center", bbox_to_anchor=(1.05, -0.42))
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, f"op_breakdown_types_{phase}.png"), dpi=130)
        plt.close(fig)
        # ---- energy: one segment per item with nonzero energy anywhere
        def val(o, key, items="energy_items"):
            v = next((i["value"] for i in o[items] if i["item"] == key), 0.0)
            return 0.0 if v == UNMODELED else v
        seen, keys = set(), []
        for o in ops:
            for it in o["energy_items"]:
                if it["value"] != UNMODELED and it["item"] not in seen:
                    seen.add(it["item"]); keys.append(it["item"])
        keys = [k for k in keys if any(val(o, k) > 0 for o in ops)]
        fig, ax = plt.subplots(figsize=(13.5, 5.4))
        bottom = np.zeros(len(ops))
        cmap = plt.cm.tab20(np.linspace(0, 1, max(len(keys), 1)))
        for k, c in zip(keys, cmap):
            vals = np.array([val(o, k) for o in ops]) * 1e6
            en = next((i.get("en", k) for o in ops for i in o["energy_items"]
                       if i["item"] == k), k)
            ax.bar(names, vals, bottom=bottom, color=c, label=en)
            bottom += vals
        ax.set_ylabel("energy per op, one layer (µJ)")
        ax.set_title(f"{result['model']} {phase}: energy per operator, every item "
                     f"separately\n(basis {result['basis']}; {result['wire_accounting']})",
                     fontsize=10)
        ax.legend(fontsize=7, ncol=2, loc="upper left", bbox_to_anchor=(1.01, 1.0))
        ax.grid(alpha=0.25, axis="y")
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, f"op_breakdown_energy_{phase}.png"), dpi=130)
        plt.close(fig)
        # ---- latency: exposed view (critical path) per op
        fig, ax = plt.subplots(figsize=(10, 4.8))
        seq = [("K/V write (serial, before compute)", "K/V write"),
               ("array compute (Timeloop cycles)", "compute"),
               ("network exposure (perfect-overlap end = max(compute, occupancy) − compute)", "network exposed (perfect overlap)"),
               ("distance propagation delay", "propagation"),
               ("die-to-die hand-off transfer (hidden state produced by this operator)", "D2D hand-off (occupancy)"),
               ("digital compute", "digital compute (elementwise ops)"),
               ("off-chip read", "off-chip read (embedding)")]
        # English labels only in figures (the container's fonts lack CJK);
        # elementwise / embedding entries are matched on their `en` label
        def lval(o, key):
            for i in o["latency_items"]:
                if (i["item"] == key or i.get("en") == key) and i["value"] != UNMODELED:
                    return i["value"]
            return 0.0
        bottom = np.zeros(len(ops))
        for (k, lbl), c in zip(seq, plt.cm.Set2(np.linspace(0, 1, len(seq)))):
            vals = np.array([lval(o, k) for o in ops]) * 1e3
            if not vals.any():
                continue
            ax.bar(names, vals, bottom=bottom, color=c, label=lbl)
            bottom += vals
        occ = np.array([lval(o, "busiest-wire occupancy (serialization)") for o in ops]) * 1e3
        ax.plot(names, occ, "kv", ms=6, label="busiest-wire occupancy (not exposed)")
        ax.set_ylabel("latency per op, one layer (ms)")
        ax.set_title(f"{result['model']} {phase}: latency per operator -- critical path "
                     f"(perfect-overlap end) + occupancy marker\n(scheme {result['scheme']}, "
                     f"{result['bw_words_per_cycle']:,.0f} words/cycle)", fontsize=10)
        ax.legend(fontsize=8)
        ax.grid(alpha=0.25, axis="y")
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, f"op_breakdown_latency_{phase}.png"), dpi=130)
        plt.close(fig)


# ---------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--S", type=int, default=512)
    ap.add_argument("--bw", type=float, default=16384.0,
                    help="macro-link bandwidth, words/cycle (platform input)")
    ap.add_argument("--scheme", default="mesh_centre", choices=sorted(SCHEMES))
    ap.add_argument("--no-shares", action="store_true",
                    help="exclusive-die mapping instead of the 48-die co-residency shares")
    ap.add_argument("--phases", default="prefill,decode")
    ap.add_argument("--no-lm-head", action="store_true",
                    help="skip the LM head mapper run (7 dies, once per model)")
    ap.add_argument("--out", default="/home/workspace/analysis/op_breakdown")
    args = ap.parse_args(argv)

    from scripts import fabric as fabric_mod
    from scripts import llm_workload as lw
    from scripts import mlx_system as mlx
    base = mlx.FABRIC
    cfg = lw.GptConfig()
    fab_scheme = _scheme_fabric(base, args.scheme, args.bw)
    result = {"model": cfg.name, "S": args.S, "n_layers": cfg.n_layers,
              "vocab": cfg.vocab,
              "basis": ("exclusive die per op" if args.no_shares
                        else "co-residency shares (48-die seating)"),
              "scheme": args.scheme, "bw_words_per_cycle": args.bw,
              "schedule_slack": _slack(),
              "wire_accounting": ("direction-split full-duplex links (bus shared); "
                                  f"partial sums {base.psum_word_bytes:g} words; "
                                  "O7 bracket both ends"),
              "fabric": base.name, "unmodeled_marker": UNMODELED, "phases": {}}
    result["digital_unit"] = dataclasses.asdict(base.digital)
    result["attention_unit"] = dataclasses.asdict(base.attention_unit)
    result["attention_unit"]["link_hops_used"] = lw.unit_link_hops(base)
    for phase in args.phases.split(","):
        d2d = _d2d_per_boundary(base, cfg, args.S, phase)
        ops = []
        for op in lw.block_ops(cfg, S=args.S, phase=phase):
            print(f"  {phase:<7} {op.name:<9} ({op.kind})", flush=True)
            r = lw.run_op(op, phase=phase,
                          share_plan=None if args.no_shares
                          else lw.SHARE_355M_48DIE[op.name])
            rec = ledger_for_op(r, phase, fab_scheme, r["result"].cycle_seconds, d2d)
            if abs(rec["energy_residual_J"]) > 1e-3 * rec["energy_total_J"]:
                print(f"    note: energy residual {rec['energy_residual_J']:.3e} J "
                      f"({rec['energy_residual_J']/rec['energy_total_J']:.2%})")
            ops.append(rec)
        # O24: the non-matmul operators of the block (closed-form, digital unit)
        for eo in lw.block_elementwise_ops(cfg, S=args.S, phase=phase):
            print(f"  {phase:<7} {eo.name:<9} (elementwise, closed-form)", flush=True)
            ops.append(ledger_for_elementwise(eo, lw.elementwise_cost(eo, base.digital),
                                              base.digital))
        # the model's two ends, once per model: embedding read, LM head matmul
        ops.append(ledger_for_embedding(lw.embedding_cost(cfg, args.S, phase, fabric=base)))
        # O9: under offload the attention runs on the external unit
        ops.append(ledger_for_attention_unit(
            lw.attention_unit_cost(cfg, args.S, phase, base.attention_unit,
                                   hops=lw.unit_link_hops(base)),
            base.attention_unit))
        if not args.no_lm_head:
            lm = lw.lm_head_op(cfg, args.S, phase)
            need = lw.dies_for_op(lm)
            have = base.level("die").per_parent if any(l.name == "die" for l in base.levels) else 1
            if need > have:
                print(f"  {phase:<7} {lm.name:<9} needs {need} dies, fabric has {have}: "
                      "marker row (run under CIMSIM_FABRIC=models/fabric/mlx300_multidie48.yaml)",
                      flush=True)
                ops.append(ledger_marker("lm_head", "static",
                                         f"the LM head needs {need} dies, the current fabric has {have}: not counted; "
                                         "run with CIMSIM_FABRIC=models/fabric/mlx300_multidie48.yaml"))
            else:
                print(f"  {phase:<7} {lm.name:<9} (static, {need} dies, once per model)",
                      flush=True)
                r = lw.run_op(lm, phase=phase, overcapacity="spatial_multi_die")
                ops.append(ledger_for_op(r, phase, fab_scheme, r["result"].cycle_seconds,
                                         (0.0, 0.0, "model-end operator, no hand-off")))
        result["phases"][phase] = {
            "ops": ops,
            "type_tables": {c: type_table(ops, cfg.n_layers, c) for c in CONDITIONS}}
    write_outputs(result, args.out)
    print(f"-> {args.out}/op_breakdown.{{json,md}}, op_breakdown_<phase>.{{csv,png}}")


if __name__ == "__main__":
    main()
