"""Per-operator cost ledger: ONE entry point, every cost item listed on its own.

For every operator of the simulated model (one transformer block per phase;
the blocks are structurally identical, so each row is also given x n_layers)
this script reports the operator's LATENCY and ENERGY and their breakdown.
Nothing is merged into coarse categories: every CiMLoop component, every
overlay term and every analytic term is its own row, with a group label
only as an annotation. Items the platform does NOT model are listed too,
with the value replaced by the marker "未建模故未统计" -- they are never
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

UNMODELED = "未建模故未统计"
OFFLOADED = "已卸载至片外单元,片上不统计(接收侧未建模,O9)"
CYC_DEFAULT = 1.449e-6
ATTN_OPS = ("qk^t", "av")                 # leave the chip under offload (with their K/V write)
CONDITIONS = {"on_chip": "attention 在片上", "offloaded": "attention 卸载(片上侧)"}
# the model's operator TYPES the platform does not simulate (whole-model view)
MODEL_UNMODELED_TYPES = []          # O24 filled the non-matmul rows (C19)
TYPE_LABEL = {"qkv_proj": "Q/K/V 投影(qkv_proj)", "qk^t": "注意力分数 QKᵀ(qk^t,含 K 写)",
              "av": "注意力加权 AV(av,含 V 写)", "out_proj": "输出投影(out_proj)",
              "ffn1": "FFN 第一层(ffn1)", "ffn2": "FFN 第二层(ffn2)",
              "softmax": "softmax(数字单元)", "gelu": "GELU(FFN 激活,数字单元)",
              "layernorm": "LayerNorm ×2(数字单元)", "residual": "残差加 ×2(数字单元)",
              "embedding": "embedding 查表(片外读,整模型一次)",
              "lm_head": "LM head(矩阵乘,最后一个 token,整模型一次)"}
PER_MODEL_OPS = ("embedding", "lm_head")      # counted once, not x n_layers

# component -> group annotation (annotation ONLY; rows are never merged)
GROUP = {
    "cim_unit": "模拟计算", "integrator": "模拟计算", "wordline_cap": "模拟计算",
    "wordline_drivers": "模拟计算", "row_drivers": "模拟计算",
    "column_drivers": "模拟计算", "weight_drivers": "模拟计算",
    "virtual_bitwise_mac": "模拟计算", "inter_1bit_x_1bit_mac_spatial": "模拟计算",
    "inter_row_spatial": "模拟计算", "inter_column_spatial": "模拟计算",
    "adc": "转换", "sample": "转换", "shift_add": "转换",
    "glb": "缓冲", "input_buffer": "缓冲", "output_buffer": "缓冲",
    "chip2chip_data_staging": "缓冲",
    "router": "片上网络", "inter_macro_in_die_spatial": "片上网络",
    "inter_core_in_macro_spatial": "片上网络",
    "inter_crossbar_in_core_spatial": "片上网络",
    "chip2chip_link": "片外端口", "here_to_fix_a_bug": "其他",
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
    ("attention 卸载后的接收单元与 die↔单元链路", "FIXLIST O9: 场景 B 只计片上侧"),
    ("core/crossbar 级链路的距离能量", "FIXLIST O1: 部件存在但无能量模型(DR-1 输入未填),下表对应行为 0"),
    ("长上下文 K/V 超容量(>~8k token)的跨 die 分片", "FIXLIST O14"),
]
LATENCY_UNMODELED = [
    ("网络排队(等峰负载向量不可区分)", "只取最忙一根线的占用;O7 区间已给两端"),
    ("attention 卸载后的接收单元与 die↔单元链路", "FIXLIST O9"),
    ("流水气泡 / 不平衡", "流水口径假设完美 microbatch 流水"),
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
            note = "无能量模型(未计价, O1)"
        items.append({"group": GROUP.get(name, "其他"), "item": f"部件 {name}",
                      "en": name, "value": e, "unit": "J", "note": note})
    # placement re-pricing beyond the flat CiMLoop charge, per component
    ov_sum = 0.0
    for name, fanout, base, hops_ratio, pa in overlay_rows:
        delta = pa - base
        ov_sum += delta
        items.append({"group": GROUP.get(name, "片上网络"),
                      "item": f"placement 距离重定价增量 {name}",
                      "en": f"placement re-pricing {name}",
                      "value": delta, "unit": "J",
                      "note": f"平均跳数/参考跳数 = {hops_ratio:.3f}"})
    items.append({"group": "写入", "item": "K/V 写编程能量", "en": "K/V write",
                  "value": write_J, "unit": "J",
                  "note": "" if write_J else "静态算子不写"})
    items.append({"group": "写入", "item": "权重重写能量(时序重写策略)",
                  "en": "weight rewrite", "value": rewrite_J, "unit": "J",
                  "note": "" if rewrite_J else "本配置未触发重写"})
    items.append({"group": "D2D", "item": "die 间交接盈余能量(超出平坦充值的跳数)",
                  "en": "D2D hand-off surplus", "value": d2d_surplus_J,
                  "unit": "J", "note": d2d_note})
    residual = cimloop_J - comp_sum
    items.append({"group": "其他", "item": "未归类残差(CiMLoop 总能量 − 各部件行之和)",
                  "en": "unlisted residual", "value": residual, "unit": "J",
                  "note": "CiMLoop 的算子总量 = 汇总表里每-compute 能量(有限精度)"
                          "× compute 数,与各部件 Energy (total) 行的精确和相差"
                          "即为该表的舍入(≤0.5%);已发表总量沿用 CiMLoop 口径"})
    for name, why in ENERGY_UNMODELED:
        items.append({"group": "未建模", "item": name, "en": name, "value": UNMODELED,
                      "unit": "", "note": why})
    return items, residual


def latency_items(compute_s, write_s, serial_s, prop_s, d2d_s=0.0,
                  d2d_note=""):
    """Every latency item of one op. Exposed amounts follow the critical
    path write + max(compute, serial) + prop (perfect overlap) and
    write + compute + serial + prop (zero overlap)."""
    exposed_max = max(compute_s, serial_s) - compute_s
    tot_max = write_s + max(compute_s, serial_s) + prop_s
    tot_sum = write_s + compute_s + serial_s + prop_s
    items = [
        {"group": "计算", "item": "阵列计算(Timeloop 周期)", "en": "compute",
         "value": compute_s, "unit": "s", "note": ""},
        {"group": "写入", "item": "K/V 写(串行,在计算前)", "en": "K/V write",
         "value": write_s, "unit": "s", "note": "" if write_s else "静态算子不写"},
        {"group": "片上网络", "item": "最忙线占用(串行化)",
         "en": "busiest-wire occupancy", "value": serial_s, "unit": "s",
         "note": "占用量,不是暴露量"},
        {"group": "片上网络", "item": "网络暴露量(完美重叠端 = max(计算,占用) − 计算)",
         "en": "network exposed (perfect overlap)", "value": exposed_max,
         "unit": "s", "note": "此前发表口径"},
        {"group": "片上网络", "item": "网络暴露量(零重叠端 = 占用)",
         "en": "network exposed (zero overlap)", "value": serial_s, "unit": "s",
         "note": "O7 区间上端"},
        {"group": "传播", "item": "距离传播延迟", "en": "propagation",
         "value": prop_s, "unit": "s", "note": ""},
        {"group": "D2D", "item": "die 间交接传输(本算子产出的隐状态)",
         "en": "D2D hand-off (occupancy)", "value": d2d_s, "unit": "s",
         "note": d2d_note},
    ]
    for name, why in LATENCY_UNMODELED:
        items.append({"group": "未建模", "item": name, "en": name, "value": UNMODELED,
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
        return 0.0, 0.0, "单 die 配置:无 die 间交接"
    if die.per_parent <= 1:
        return 0.0, 0.0, "单 die 配置:无 die 间交接"
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
            "die 链路未设带宽(出厂默认):传输时间记 0"
    t = words / bw * CYC_DEFAULT
    return t, d["energy_J"] / max(d["n_boundaries"], 1), \
        f"蛇形摆放,{n} 单元链,die 链路 {bw:,.0f} 词/周期;单遍口径下藏在整栈计算后"


def ledger_for_elementwise(eo, cost, digital):
    """Ledger entry of one non-matmul operator (O24): energy = glb passes +
    digital arithmetic, latency = digital time (serial with the matmuls)."""
    e_items = [
        {"group": "缓冲", "item": f"glb 读写({eo.glb_passes} 趟 × {eo.elements:,} 元素)",
         "en": "glb passes", "value": cost["glb_J"], "unit": "J",
         "note": f"glb {lw_glb_note()}"},
        {"group": "数字单元", "item": "数字单元算术(加/乘/查表)", "en": "digital arithmetic",
         "value": cost["arith_J"], "unit": "J",
         "note": f"每元素 {eo.adds:g} 加 + {eo.muls:g} 乘 + {eo.luts:g} 查表;{digital.calibration}"},
    ]
    for name, why in ENERGY_UNMODELED:
        e_items.append({"group": "未建模", "item": name, "en": name, "value": UNMODELED,
                        "unit": "", "note": why})
    l_items = [
        {"group": "数字单元", "item": f"数字单元计算({eo.arith_ops:,.0f} 次算术 ÷ {digital.lanes} 通道 × {digital.clock_hz/1e9:g} GHz)",
         "en": "digital compute", "value": cost["latency_s"], "unit": "s",
         "note": "与相邻矩阵乘串行(假设,已陈述)"},
        {"group": "片上网络", "item": "最忙线占用(串行化)", "en": "busiest-wire occupancy",
         "value": 0.0, "unit": "s", "note": "数字单元挂在 glb 旁,不走片上网络(假设)"},
    ]
    for name, why in LATENCY_UNMODELED:
        l_items.append({"group": "未建模", "item": name, "en": name, "value": UNMODELED,
                        "unit": "", "note": why})
    return {"op": eo.name, "kind": "elementwise",
            "shape": {"elements": eo.elements, "after": eo.after},
            "energy_total_J": cost["energy_J"], "energy_residual_J": 0.0,
            "energy_items": e_items,
            "latency_total_s": {"perfect_overlap_s": cost["latency_s"],
                                "zero_overlap_s": cost["latency_s"]},
            "latency_items": l_items, "network_bound": False, "bottleneck_wire": None}


def ledger_for_embedding(emb):
    lat = emb["latency_s"]
    e_items = [{"group": "片外", "item": f"片外读 {emb['words']:,} 词 × DRAM 每词能量",
                "en": "off-chip read", "value": emb["energy_J"], "unit": "J", "note": ""}]
    l_items = [{"group": "片外", "item": "片外读传输", "en": "off-chip read",
                "value": lat if lat is not None else 0.0, "unit": "s",
                "note": "" if emb["timed"] else "片外端口带宽未设(fabric.offchip_bandwidth_words_per_cycle):计价不计时"}]
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
            "energy_items": [{"group": "未统计", "item": why, "en": "not counted",
                              "value": UNMODELED, "unit": "", "note": why}],
            "latency_total_s": {"perfect_overlap_s": 0.0, "zero_overlap_s": 0.0},
            "latency_items": [{"group": "未统计", "item": why, "en": "not counted",
                               "value": UNMODELED, "unit": "", "note": why}],
            "network_bound": False, "bottleneck_wire": None, "marker": why}


def lw_glb_note():
    return "每词访问能量取自同一 die 的 CiMLoop 校准值(ffn1 fixture 15.47 pJ/词)"


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
    d2d_note = note if ends_unit else "本算子不在单元边界(交接归 out_proj / ffn2)"
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
                         "latency_zero_overlap_s": OFFLOADED, "note": OFFLOADED})
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
    rows.append({"type": "已统计合计(矩阵乘 + 数字单元算子 + 片外读)", "op": "", "energy_J": E,
                 "energy_share": 1.0, "latency_s": L1, "latency_share": 1.0,
                 "latency_zero_overlap_s": L2, "note": "占比以此为分母"})
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
        json.dump(result, f, indent=1, ensure_ascii=False)
    md = ["# 按算子的开销账本", "",
          f"模型 {result['model']},S={result['S']},{result['n_layers']} 层;"
          f"基线:{result['basis']};走线方案 {result['scheme']},链路带宽 "
          f"{result['bw_words_per_cycle']:,.0f} 词/周期(平台输入);记账:{result['wire_accounting']}。",
          "每行一项,不合并;标 **" + UNMODELED + "** 的项平台未建模。", ""]
    for phase, ph in result["phases"].items():
        n = result["n_layers"]
        md += [f"## {phase}", ""]
        for cond, tt in ph["type_tables"].items():
            md += [f"### 算子类型 × 整模型占比 —— {tt['condition']}", "",
                   "| 算子类型 | 整模型能量(mJ) | 能量占比 | 整模型延迟(ms,完美重叠端) | 延迟占比 | 整模型延迟(ms,零重叠端) | 备注 |",
                   "|---|---|---|---|---|---|---|"]
            for r in tt["rows"]:
                if isinstance(r["energy_J"], str):
                    md.append(f"| {r['type']} | {r['energy_J']} | | {r['latency_s']} | | | {r['note']} |")
                else:
                    md.append(f"| {r['type']} | {r['energy_J']*1e3:,.3f} | {r['energy_share']:.1%} | "
                              f"{r['latency_s']*1e3:,.2f} | {r['latency_share']:.1%} | "
                              f"{r['latency_zero_overlap_s']*1e3:,.2f} | {r['note']} |")
            md.append("")
        md += ["### 每算子总量(一层 / ×层数,逐算子数据与条件无关)", "",
               "| 算子 | 类型 | 总能量(µJ) | 整模型能量(mJ) | 延迟·完美重叠端(ms) | 延迟·零重叠端(ms) | 整模型延迟·完美重叠端(ms) | 网络受限 |",
               "|---|---|---|---|---|---|---|---|"]
        for o in ph["ops"]:
            md.append(f"| {o['op']} | {o['kind']} | {o['energy_total_J']*1e6:,.2f} | "
                      f"{o['energy_total_J']*n*1e3:,.3f} | "
                      f"{o['latency_total_s']['perfect_overlap_s']*1e3:,.4f} | "
                      f"{o['latency_total_s']['zero_overlap_s']*1e3:,.4f} | "
                      f"{o['latency_total_s']['perfect_overlap_s']*n*1e3:,.2f} | "
                      f"{'是' if o['network_bound'] else '否'} |")
        E = sum(o["energy_total_J"] for o in ph["ops"]) * n
        L1 = sum(o["latency_total_s"]["perfect_overlap_s"] for o in ph["ops"]) * n
        L2 = sum(o["latency_total_s"]["zero_overlap_s"] for o in ph["ops"]) * n
        md += ["", f"整模型合计:能量 {E*1e3:,.3f} mJ;延迟 {L1*1e3:,.2f} ms(完美重叠端)"
               f" / {L2*1e3:,.2f} ms(零重叠端)。", ""]
        for o in ph["ops"]:
            shape = ",".join(f"{k}={v:,}" if isinstance(v, int) else f"{k}={v}"
                             for k, v in o["shape"].items())
            md += [f"### {phase} · {o['op']}({o['kind']}{',' + shape if shape else ''})", "",
                   "能量:", "", "| 组 | 项 | 值 | 占算子总能量 | 备注 |", "|---|---|---|---|---|"]
            for it in o["energy_items"]:
                share = "" if it["value"] == UNMODELED or o["energy_total_J"] == 0 \
                    else f"{it['value']/o['energy_total_J']:.2%}"
                md.append(f"| {it['group']} | {it['item']} | {_num(it['value'], it['unit'])} | {share} | {it['note']} |")
            md += ["", "延迟:", "", "| 组 | 项 | 值 | 备注 |", "|---|---|---|---|"]
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
        seq = [("K/V 写(串行,在计算前)", "K/V write"),
               ("阵列计算(Timeloop 周期)", "compute"),
               ("网络暴露量(完美重叠端 = max(计算,占用) − 计算)", "network exposed (perfect overlap)"),
               ("距离传播延迟", "propagation"),
               ("die 间交接传输(本算子产出的隐状态)", "D2D hand-off (occupancy)"),
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
        occ = np.array([lval(o, "最忙线占用(串行化)") for o in ops]) * 1e3
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
              "wire_accounting": ("direction-split full-duplex links (bus shared); "
                                  f"partial sums {base.psum_word_bytes:g} words; "
                                  "O7 bracket both ends"),
              "fabric": base.name, "unmodeled_marker": UNMODELED, "phases": {}}
    result["digital_unit"] = dataclasses.asdict(base.digital)
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
        if not args.no_lm_head:
            lm = lw.lm_head_op(cfg, args.S, phase)
            need = lw.dies_for_op(lm)
            have = base.level("die").per_parent if any(l.name == "die" for l in base.levels) else 1
            if need > have:
                print(f"  {phase:<7} {lm.name:<9} needs {need} dies, fabric has {have}: "
                      "marker row (run under CIMSIM_FABRIC=models/fabric/mlx300_multidie48.yaml)",
                      flush=True)
                ops.append(ledger_marker("lm_head", "static",
                                         f"LM head 需 {need} 个 die,当前 fabric 只有 {have} 个:未统计;"
                                         "用 CIMSIM_FABRIC=models/fabric/mlx300_multidie48.yaml 运行"))
            else:
                print(f"  {phase:<7} {lm.name:<9} (static, {need} dies, once per model)",
                      flush=True)
                r = lw.run_op(lm, phase=phase, overcapacity="spatial_multi_die")
                ops.append(ledger_for_op(r, phase, fab_scheme, r["result"].cycle_seconds,
                                         (0.0, 0.0, "整模型末端算子,无交接")))
        result["phases"][phase] = {
            "ops": ops,
            "type_tables": {c: type_table(ops, cfg.n_layers, c) for c in CONDITIONS}}
    write_outputs(result, args.out)
    print(f"-> {args.out}/op_breakdown.{{json,md}}, op_breakdown_<phase>.{{csv,png}}")


if __name__ == "__main__":
    main()
