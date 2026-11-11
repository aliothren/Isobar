"""Attention offload (the agreed setting): the dynamic attention (QK^T,
softmax, AV) and the K/V cache leave the ReRAM arrays for a digital unit
inside the package, the "hub"; the static projections and the FFN stay on
the CIM dies. This module holds the configuration object the evaluator,
the baselines and the search consume, and the closed-form unit costs.

Model (search_eval, with offload set on the workload):
  - a unit is a DEDICATED node of the die grid (it occupies one slot, which
    no die-set may take) at a declared position: 'center' (the mesh hub
    position), 'edge', 'corner', or K units at the centres of K equal
    regions (K = 2 halves along the longer axis, K = 4 quadrants);
  - every layer is served by one unit (a contiguous layer -> unit map);
    layers run one after another, so the unit's time per layer adds to the
    placement-independent term R: unit compute (the MACs of QK^T and AV
    plus the softmax element operations at the unit's rate, plus the
    per-call overhead) and the K/V memory time (the new tokens' K/V
    written, the whole context's K/V read, at the K/V bandwidth);
  - the hand-offs qkv_proj -> unit (the whole QKV output of the layer; the
    producers' pieces, or their partial sums at the partial-sum width when
    qkv_proj is row-split) and unit -> out_proj (the attention output to
    every out_proj die) are ordinary node-to-node flows on the die mesh at
    the mesh link bandwidth B_mesh; the unit's node has its own
    injection/ejection capacity C_hub per direction (the hub interface),
    the dies keep kappa B_mesh; a hand-off's service time is the busiest
    of its links, die ports and hub ports under their own capacities;
  - energy: the unit's MACs at pj_per_mac, the K/V words at the memory's
    read/write pJ, the flows at the die-link pJ per word per hop (the same
    rule as every other hand-off);
  - K/V capacity: the whole active working set of the layers a unit serves
    (2 x batch x layers x cache length x n_kv_heads x head_dim x bytes)
    must fit the unit's K/V memory;
  - 'total' resource mode shares one budget over K units (rate, K/V
    bandwidth and capacity, hub interface each divided by K); 'per_unit'
    gives every unit the reference parameters.
"""
import dataclasses as dc
from typing import Dict, Optional, Tuple

REF_UNIT = {"mac_per_second": 2.0e12, "pj_per_mac": 1.0, "call_overhead_s": 0.0,
            "kv_words_per_second": 25.6e9, "kv_pj_per_word_read": 50.0, "kv_pj_per_word_write": 50.0,
            "kv_capacity_words": 2.0e9, "link_bandwidth_gbps": 12.5, "link_pj_per_word": 10.0,
            "bytes_per_kv_element": 1,        # 8-bit K/V values, the word of every account
            "buffer_bytes": 8.0e6,            # the unit's own working buffer (edge-NPU class: 8 MB on-chip SRAM); an explicit assumption
            "score_bytes": 2, "prob_bytes": 1,  # a score (pre-softmax, 16-bit accumulate) and a probability (8-bit) per (query, key) pair
            "algorithm": "auto"}              # 'materialized' | 'tiled' | 'auto' (the cheaper of the two per workpoint)


@dc.dataclass
class OffloadConfig:
    unit: Dict[str, float]            # effective parameters of ONE unit (after the resource mode)
    hubs: Tuple[int, ...]             # unit node ids (die-grid slots)
    layer_unit: Tuple[int, ...]       # unit index per layer (layer-group mode)
    spec: Dict[str, object]           # the declared spec (position, K, mode, overrides) for the record
    co_located: bool = False          # True: the unit shares a die's slot (not reserved)
    split: str = "layer"              # 'layer': one unit per layer; 'head': every layer over all K units, complete K/V-head groups per unit

    def unit_node(self, li: int) -> int:
        return self.hubs[self.layer_unit[li]]

    def unit_nodes(self, li: int):
        """The endpoints of layer li's attention: one unit (layer mode) or all K (head mode)."""
        return list(self.hubs) if self.split == "head" else [self.hubs[self.layer_unit[li]]]

    @property
    def K(self):
        return len(self.hubs)

    def reserved_slots(self):
        return set() if self.co_located else set(self.hubs)

    def hub_ratio(self, bw_gbps: float) -> float:
        """C_hub / B_mesh: hub port loads in link-time units are divided by this."""
        return self.unit["link_bandwidth_gbps"] / bw_gbps

    def to_json(self):
        return {"unit": self.unit, "hubs": list(self.hubs), "layer_unit": list(self.layer_unit), "spec": self.spec, "co_located": self.co_located, "split": self.split}


def hub_slots(slots_xy, position: str, K: int = 1):
    """Unit node ids: the slots nearest the declared positions."""
    xs = [s[0] for s in slots_xy]; ys = [s[1] for s in slots_xy]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if K == 1:
        targets = {"center": [(cx, cy)], "edge": [(x0, cy)], "corner": [(x0, y0)]}[position]
    elif K == 2:
        if (x1 - x0) >= (y1 - y0):
            targets = [((x0 + cx) / 2, cy), ((cx + x1) / 2, cy)]
        else:
            targets = [(cx, (y0 + cy) / 2), (cx, (cy + y1) / 2)]
    elif K == 4:
        targets = [((x0 + cx) / 2, (y0 + cy) / 2), ((cx + x1) / 2, (y0 + cy) / 2),
                   ((x0 + cx) / 2, (cy + y1) / 2), ((cx + x1) / 2, (cy + y1) / 2)]
    else:
        raise ValueError(f"K = {K}: positions declared for 1, 2 and 4 units")
    out = []
    for tx, ty in targets:
        cand = sorted(range(len(slots_xy)), key=lambda i: (abs(slots_xy[i][0] - tx) + abs(slots_xy[i][1] - ty), i))
        out.append(next(i for i in cand if i not in out))
    return out


def layer_map(n_layers: int, K: int):
    """Contiguous layer groups: unit u serves layers [u L/K, (u+1) L/K)."""
    return tuple(min(K - 1, li * K // n_layers) for li in range(n_layers))


def build(slots_xy, n_layers: int, position: str = "center", K: int = 1, resource_mode: str = "per_unit",
          overrides: Optional[Dict[str, float]] = None, co_located: bool = False, split: str = "layer") -> OffloadConfig:
    unit = dict(REF_UNIT); unit.update(overrides or {})
    if resource_mode == "total":
        for k in ("mac_per_second", "kv_words_per_second", "kv_capacity_words", "link_bandwidth_gbps", "buffer_bytes"):
            unit[k] = unit[k] / K
    elif resource_mode != "per_unit":
        raise ValueError(resource_mode)
    if split not in ("layer", "head"):
        raise ValueError(split)
    return OffloadConfig(unit=unit, hubs=tuple(hub_slots(slots_xy, position, K)), layer_unit=layer_map(n_layers, K),
                         spec={"position": position, "K": K, "resource_mode": resource_mode, "overrides": dict(overrides or {}), "split": split},
                         co_located=co_located, split=split)


def attention_algorithm(cfg, S: int, phase: str, unit: Dict[str, float], heads: Optional[int] = None, context: Optional[int] = None):
    """The unit's attention algorithm and its working set, head by head.
    materialized: a head's P x ctx scores (score_bytes) and probabilities
    (prob_bytes) are formed whole; if they exceed the unit's buffer they are
    spilled to the K/V memory (written and read back once each) and the
    memory holds one head's working set beside the cache. tiled: the
    queries are processed in tiles whose scores fit the buffer, so nothing
    spills, but every tile re-reads the head's K and V (n_tiles reads per
    layer instead of one). 'auto' takes the cheaper memory traffic. Returns
    the traffic and workspace terms for ONE unit's share of the layer."""
    Pq = S if phase == "prefill" else 1
    ctx = S if context is None else context
    H = cfg.n_heads if heads is None else heads
    dh = cfg.dh
    per_pair = unit["score_bytes"] + unit["prob_bytes"]
    ws_head = Pq * ctx * per_pair                       # one head's scores + probabilities
    buf = unit["buffer_bytes"]
    # materialized
    spill = ws_head > buf
    mat_traffic = (2 * ws_head * H) if spill else 0.0   # written and read back, every head
    mat_workspace = ws_head if spill else 0.0
    # tiled
    P_tile = max(1, int(buf // max(1, ctx * per_pair)))
    n_tiles = -(-Pq // P_tile)
    kv_extra = (n_tiles - 1) * 2 * ctx * dh * H         # K and V re-read for every tile beyond the first (per head, all heads)
    choice = unit.get("algorithm", "auto")
    if choice == "auto":
        choice = "tiled" if kv_extra < mat_traffic else "materialized"
    if choice == "materialized":
        return {"algorithm": "materialized", "scores_materialized": True, "spill": spill, "workspace_bytes_per_head": ws_head,
                "extra_memory_words": mat_traffic, "workspace_bytes": mat_workspace, "kv_reads_per_layer": 1, "P_tile": Pq, "n_tiles": 1}
    return {"algorithm": "tiled", "scores_materialized": False, "spill": False, "workspace_bytes_per_head": min(ws_head, P_tile * ctx * per_pair),
            "extra_memory_words": kv_extra, "workspace_bytes": 0.0, "kv_reads_per_layer": n_tiles, "P_tile": P_tile, "n_tiles": n_tiles}


def unit_layer_cost(cfg, S: int, phase: str, unit: Dict[str, float], context: Optional[int] = None, heads: Optional[int] = None, kv_heads: Optional[int] = None):
    """One layer's share on ONE unit: compute (QK^T and AV MACs over the
    context plus the softmax element operations, at the unit's rate, plus
    the per-call overhead), K/V memory time (write the new tokens' K and V,
    read the context's K and V once, plus the algorithm's extra traffic:
    spilled scores or re-read K/V) and the two energies. Link time and
    energy are NOT here (the flows carry them). `heads` / `kv_heads` = the
    unit's share in head-split mode (default: the whole layer)."""
    Pq = S if phase == "prefill" else 1
    ctx = S if context is None else context
    H = cfg.n_heads if heads is None else heads
    Hkv = cfg.kv_heads if kv_heads is None else kv_heads
    dh = cfg.dh
    alg = attention_algorithm(cfg, S, phase, unit, heads=H, context=ctx)
    macs = 2 * Pq * ctx * H * dh                     # QK^T and AV, this unit's heads
    softmax_ops = H * Pq * ctx * 4                   # 2 adds + 1 mul + 1 lookup per score
    ops = macs + softmax_ops
    compute_s = ops / unit["mac_per_second"] + unit["call_overhead_s"]
    compute_J = ops * unit["pj_per_mac"] * 1e-12
    kv_write_words = 2 * Pq * Hkv * dh               # the new tokens' K and V
    kv_read_words = 2 * ctx * Hkv * dh * alg["kv_reads_per_layer"]   # the context, once (or once per query tile)
    extra = alg["extra_memory_words"]
    kv_s = (kv_write_words + kv_read_words + extra) / unit["kv_words_per_second"]
    kv_J = (kv_write_words * unit["kv_pj_per_word_write"] + kv_read_words * unit["kv_pj_per_word_read"]
            + extra * 0.5 * (unit["kv_pj_per_word_read"] + unit["kv_pj_per_word_write"])) * 1e-12
    return {"macs": macs, "softmax_ops": softmax_ops, "compute_s": compute_s, "compute_J": compute_J,
            "kv_write_words": kv_write_words, "kv_read_words": kv_read_words, "extra_memory_words": extra, "kv_s": kv_s, "kv_J": kv_J,
            "unit_s": compute_s + kv_s, "energy_J": compute_J + kv_J, "algorithm": alg}


def kv_capacity(cfg, S: int, off: OffloadConfig, batch: int = 1, phase: str = "prefill"):
    """Per unit: the K/V working set of the layers (or heads) it serves plus
    the algorithm's workspace vs its memory."""
    K = off.K
    out = []
    for u in range(K):
        if off.split == "head":
            n_layers, hkv = cfg.n_layers, cfg.kv_heads // K
            heads = cfg.n_heads // K
        else:
            n_layers, hkv, heads = sum(1 for x in off.layer_unit if x == u), cfg.kv_heads, cfg.n_heads
        per_layer = 2 * batch * S * hkv * cfg.dh * off.unit["bytes_per_kv_element"]
        alg = attention_algorithm(cfg, S, phase, off.unit, heads=heads)
        need = per_layer * n_layers + alg["workspace_bytes"]
        out.append({"unit": u, "layers": n_layers, "kv_heads": hkv, "kv_bytes": per_layer * n_layers, "workspace_bytes": alg["workspace_bytes"],
                    "algorithm": alg["algorithm"], "capacity_bytes": off.unit["kv_capacity_words"], "fits": need <= off.unit["kv_capacity_words"]})
    return out


def head_groups(cfg, K: int):
    """Complete K/V-head groups per unit (head mode): unit u takes query heads
    [u H/K, (u+1) H/K) and K/V heads [u Hkv/K, (u+1) Hkv/K)."""
    if cfg.n_heads % K or cfg.kv_heads % K:
        raise ValueError(f"head split: {cfg.n_heads} query heads / {cfg.kv_heads} K/V heads do not divide by {K}")
    return [{"q_heads": (u * cfg.n_heads // K, (u + 1) * cfg.n_heads // K), "kv_heads": (u * cfg.kv_heads // K, (u + 1) * cfg.kv_heads // K)} for u in range(K)]
