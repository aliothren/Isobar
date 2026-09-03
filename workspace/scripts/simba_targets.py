"""Simba reproduction targets (C44, worklist step 1, day 5): the T1
seating-spread experiment, governed by SIMBA_PREREG amendment A1.

T1 = MICRO'19 §4.6 / Fig 9: res4a_branch1 on four chiplets, tiling
frozen, only the seating varies. The five seatings are the DECODED
figure diagrams (extracts §C): expanding squares anchored at (0,0),
side 1..5. Everything here is closed form on the frozen simba-repro
fabric: no mapper, no simulator.

Occupancy: node-to-node flows with MULTICAST DEDUP (A1-d) -- one IA
slice multicast to its K-group charges each shared route segment once
(Simba's multicast is physical: one-hot addressing, cut-through);
partial-sum flows are distinct data and sum per segment at
psum_word_bytes width. Busiest segment's volume / link bandwidth =
the serialization bound; latency = [max, sum](compute, serialization)
+ longest-path propagation at 20 ns/hop.
"""
import json
import os
from typing import Dict, List, Sequence, Tuple

from scripts import interconnect as ic_mod
from scripts.simba_workload import (RESNET50, compute_seconds,
                                    conv_structure, simba_fabric)
from scripts.traffic import IN_DISTINCT, OUT_REDUCED, _prod

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# Fig 9's five seatings, decoded from the figure (extracts §C), as
# (x, y) = (col, row) on the 6x6 NoP mesh; anchor first (A1-b).
FIG9_SEATINGS: List[List[Tuple[int, int]]] = [
    [(0, 0), (0, k), (k, 0), (k, k)] for k in range(1, 6)
]
# the figure's bars, pixel-read +-0.01 (extracts §C)
FIG9_MEASURED = [1.000, 1.359, 1.739, 2.122, 2.530]

T1_LAYER = "res4a_branch1"


def _die_nodes(fabric, seating: Sequence[Tuple[int, int]]) -> List[int]:
    """Seat coordinates -> node indices of the row-major die slot table."""
    mx, _ = fabric.level("die").mesh
    return [y * mx + x for (x, y) in seating]


def _coord_groups(split, keep) -> List[List[int]]:
    """Instance indices grouped by the kept dims' coordinates, under the
    C38 index convention (last listed dim varies fastest)."""
    dims = list(split.factors.items())
    groups: Dict[tuple, List[int]] = {}
    for i in range(split.fanout):
        rem, coord = i, []
        for name, f in reversed(dims):
            coord.append((name, rem % f))
            rem //= f
        key = tuple(v for name, v in coord if name in keep)
        groups.setdefault(key, []).append(i)
    return [sorted(g) for g in groups.values()]


def _packet_bracket(lv, ser, comp, pkt_flows):
    """A3: overhead-tightened serialization + the round-serialized end.
    pkt_flows = [(src, h, vol_bytes)]; per source the terms SUM (one
    manager issues serially), across sources take the MAX (parallel
    managers); the pessimistic end composes by SUM and absorbs
    propagation (its first round is the head's propagation)."""
    import math
    ser = ser * lv.link.packet_wire_overhead
    payload = lv.link.packet_payload_bytes
    if payload is None:
        return ser, 0.0, None
    per_src: Dict[int, float] = {}
    for src, h, vol in pkt_flows:
        if vol <= 0 or h <= 0:
            continue
        n_pkt = math.ceil(vol / payload)
        per_src[src] = per_src.get(src, 0.0) + n_pkt * h * lv.link.ns_per_hop * 1e-9
    pkt = max(per_src.values(), default=0.0)
    return ser, pkt, comp + ser + pkt


def t1_candidate_splits(op) -> List[Dict[str, int]]:
    """A1's enumeration rule: power-of-two factorizations of 4 dies over
    {K, C} plus P/Q where exact (R=1) and divisible."""
    out = []
    dims_ok = ["K", "C"] + (["P", "Q"] if op.R == 1 and op.S == 1 else [])
    size = {"K": op.K, "C": op.C, "P": op.P, "Q": op.Q}
    combos = [{d: 4} for d in dims_ok]
    combos += [{a: 2, b: 2} for i, a in enumerate(dims_ok)
               for b in dims_ok[i + 1:]]
    for cand in combos:
        if all(size[d] % f == 0 for d, f in cand.items()):
            out.append(cand)
    return out


def t1_evaluate(op, die_split: Dict[str, int],
                seating: Sequence[Tuple[int, int]], fabric=None) -> dict:
    """Latency of `op` under `die_split` on one seating (A1 semantics)."""
    from scripts import placement as placement_mod
    fab = fabric or simba_fabric()
    lv = fab.level("die")
    pl = placement_mod.sequential_fill(fab)
    ic = ic_mod.build(fab, "die", pl)
    nodes = _die_nodes(fab, seating)
    src = nodes[0]                                     # IA home = anchor (A1-a)

    ts = conv_structure(op, die_split=die_split, fabric=fab)
    split = ts.splits[0]
    assert split.level == "die" and split.fanout == len(nodes)
    ev = ts.edge_volumes()["die"]

    load: Dict[str, float] = {}
    pkt_flows = []                                     # (src, h, vol_bytes) A3
    # IA multicast: instances sharing every IN-DISTINCT coordinate get the
    # SAME slice; the slice's route segments are charged ONCE (dedup, A1-d)
    keep_in = {d for d in split.factors if d in IN_DISTINCT}
    for group in _coord_groups(split, keep_in):
        segs = set()
        h = 0.0
        for gi in group:
            m = nodes[gi]
            if m != src:
                segs |= set(ic.path_directed(src, m))
                h = max(h, ic.hops(src, m))
        for r, tag in segs:
            key = f"{r}/{tag}" if tag else r
            load[key] = load.get(key, 0.0) + ev["in"]
        if segs:
            pkt_flows.append((src, h, ev["in"]))
    # partial sums: reduction hyperedge members -> first-member owner,
    # distinct data, psum width (A1-c); pure K splits produce none
    keep_out = {d for d in split.factors if d not in OUT_REDUCED}
    psum_w = float(getattr(fab, "psum_word_bytes", 2.0))
    for group in _coord_groups(split, keep_out):
        owner = nodes[group[0]]
        for gi in group[1:]:
            m = nodes[gi]
            for r, tag in ic.path_directed(m, owner):
                key = f"{r}/{tag}" if tag else r
                load[key] = load.get(key, 0.0) + ev["out"] * psum_w
            pkt_flows.append((m, ic.hops(m, owner), ev["out"] * psum_w))

    bw = lv.link.bandwidth_words_per_cycle             # words / device cycle
    cyc = fab.device.cycle_seconds
    slack = fab.schedule_slack
    busiest = max(load.values(), default=0.0)
    ser0 = busiest / bw * cyc * slack if bw else 0.0
    comp = compute_seconds(op, len(nodes), fabric=fab)
    ser, pkt, pess = _packet_bracket(lv, ser0, comp, pkt_flows)
    hops = max((ic.hops(src, n) for n in nodes if n != src), default=0.0)
    prop = hops * lv.link.ns_per_hop * 1e-9
    return {"compute_s": comp, "serialization_s": ser, "prop_s": prop,
            "max_hops": hops, "busiest_words": busiest,
            "packet_term_s": pkt,
            "latency_max_end_s": max(comp, ser) + prop,
            "latency_sum_end_s": comp + ser + prop,
            "latency_pess_s": pess}


def t1_run(fabric=None) -> dict:
    """The full T1 experiment: A1's enumeration at the reference seating
    freezes the tiling; the five decoded seatings are then evaluated."""
    fab = fabric or simba_fabric()
    op = RESNET50[T1_LAYER]
    scored = []
    for cand in t1_candidate_splits(op):
        r = t1_evaluate(op, cand, FIG9_SEATINGS[0], fabric=fab)
        scored.append((r["latency_max_end_s"], sorted(cand.items()), cand, r))
    scored.sort(key=lambda t: (t[0], t[1]))            # deterministic tie-break
    frozen = scored[0][2]

    rows = []
    for seating, measured in zip(FIG9_SEATINGS, FIG9_MEASURED):
        r = t1_evaluate(op, frozen, seating, fabric=fab)
        rows.append({"seating": seating, "measured_norm": measured, **r})
    base = rows[0]
    for r in rows:
        r["ratio_max_end"] = r["latency_max_end_s"] / base["latency_max_end_s"]
        r["ratio_sum_end"] = r["latency_sum_end_s"] / base["latency_sum_end_s"]
    for r in rows:
        if rows[0].get("latency_pess_s"):
            r["ratio_pess"] = r["latency_pess_s"] / rows[0]["latency_pess_s"]
    lat = [r["latency_max_end_s"] for r in rows]
    pess_ratio = rows[-1].get("ratio_pess")
    # A3 sensitivity note: the enumeration re-scored at the PESSIMISTIC
    # end (tilings stay frozen per A1; recorded only)
    resc = []
    for cand in t1_candidate_splits(op):
        rr = t1_evaluate(op, cand, FIG9_SEATINGS[0], fabric=fab)
        if rr.get("latency_pess_s"):
            resc.append((rr["latency_pess_s"], sorted(cand.items()), cand))
    resc.sort(key=lambda t: (t[0], t[1]))
    result = {
        "layer": T1_LAYER, "frozen_split": frozen,
        "enumeration": [{"split": c, "latency_max_end_s": s}
                        for s, _, c, _ in scored],
        "pess_rescore_argmin": resc[0][2] if resc else None,
        "rows": rows,
        "T1a_strictly_increasing": all(a < b for a, b in zip(lat, lat[1:])),
        "T1b_ratio": rows[-1]["ratio_max_end"],
        "T1b_band": [1.265, 5.06],
        "T1b_pass": 1.265 <= rows[-1]["ratio_max_end"] <= 5.06,
        "T1b_ratio_pess": pess_ratio,
        "T1b_pess_in_band": (pess_ratio is not None
                             and 1.265 <= pess_ratio <= 5.06),
        "bracket_bar5": [rows[-1]["ratio_max_end"], pess_ratio],
    }
    return result


def main():
    res = t1_run()
    out = os.path.join(WS, "analysis", "simba_t1.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=1)
    print(f"frozen tiling: {res['frozen_split']}")
    print("enumeration (max-end latency at the reference seating):")
    for e in res["enumeration"]:
        print(f"  {e['split']}: {e['latency_max_end_s'] * 1e6:.3f} us")
    print("\nbar  seating                          meas   ours(max-end)   ratio      ser_us  comp_us  prop_ns")
    for i, r in enumerate(res["rows"], 1):
        print(f"  {i}  {str(r['seating']):<32} {r['measured_norm']:.3f}  "
              f"{r['latency_max_end_s'] * 1e6:10.4f} us  {r['ratio_max_end']:.6f}  "
              f"{r['serialization_s'] * 1e6:7.3f}  {r['compute_s'] * 1e6:7.3f}  "
              f"{r['prop_s'] * 1e9:6.1f}")
    print(f"\nT1a strictly increasing: {res['T1a_strictly_increasing']}")
    print(f"T1b ratio bar5/bar1: {res['T1b_ratio']:.7f}  band {res['T1b_band']}"
          f"  -> {'PASS' if res['T1b_pass'] else 'FAIL (triage)'}")


if __name__ == "__main__":
    main()


# ======================================================================
# T2 (C45, day 6): the Fig 15 data-placement experiment, governed by A2.
# Placement moves DATA blocks (IA/OA homes among Global PEs); work
# assignment and tiling stay fixed. Baseline = Fig 14(b) sequential;
# greedy = the paper's stated objective with the A2-declared procedure.
# ======================================================================

# A2-1: the 32 active dies = row-major first 32 slots = node indices 0..31
T2_ACTIVE = list(range(32))
T2_LAYERS = ["res3a_branch1", "res2[a-c]_branch2c", "res4a_branch1",
             "res2[a-c]_branch2b", "res5[a-c]_branch2b", "res4[b-f]_branch2a"]
T2_CENTER_NODE = 2 * 6 + 2          # (2,2), A2-8's declared center


def _mcast_segs(ic, src: int, members: Sequence[int]) -> set:
    segs = set()
    for m in members:
        if m != src:
            segs |= set(ic.path_directed(src, m))
    return segs


def _t2_blocks(op, die_split, fabric):
    ts = conv_structure(op, die_split=die_split, fabric=fabric)
    split = ts.splits[0]
    ia_groups = _coord_groups(split, {d for d in split.factors
                                      if d in IN_DISTINCT})
    oa_groups = _coord_groups(split, {d for d in split.factors
                                      if d not in OUT_REDUCED})
    reduced = any(d in OUT_REDUCED for d in split.factors)
    return ts, ia_groups, oa_groups, reduced


def t2_candidate_splits(op, n_dies: int = 32) -> List[Dict[str, int]]:
    """A2-2: power-of-two factorizations of n_dies over {K, C} plus P/Q
    where exact (R=S=1) and divisible."""
    dims_ok = ["K", "C"] + (["P", "Q"] if op.R == 1 and op.S == 1 else [])
    size = {"K": op.K, "C": op.C, "P": op.P, "Q": op.Q}
    out = []

    def rec(i, remaining, cur):
        if remaining == 1:
            out.append({d: f for d, f in cur.items() if f > 1})
            return
        if i == len(dims_ok):
            return
        d = dims_ok[i]
        f = 1
        while f <= remaining:
            if remaining % f == 0 and size[d] % f == 0:
                cur[d] = f
                rec(i + 1, remaining // f, cur)
            f *= 2
        cur.pop(d, None)

    rec(0, n_dies, {})
    uniq = {tuple(sorted(c.items())): c for c in out}
    return list(uniq.values())


def t2_evaluate(op, die_split: Dict[str, int], ia_homes: Sequence[int],
                oa_homes: Sequence[int], fabric=None,
                active: Sequence[int] = None) -> dict:
    """Latency under one data placement (A2-6 flow semantics)."""
    from scripts import placement as placement_mod
    fab = fabric or simba_fabric()
    lv = fab.level("die")
    ic = ic_mod.build(fab, "die", placement_mod.sequential_fill(fab))
    act = list(active if active is not None else T2_ACTIVE)

    ts, ia_groups, oa_groups, reduced = _t2_blocks(op, die_split, fab)
    assert ts.splits[0].fanout == len(act)
    ev = ts.edge_volumes()["die"]
    width = float(getattr(fab, "psum_word_bytes", 2.0)) if reduced else 1.0

    load: Dict[str, float] = {}
    hops_seen = [0.0]
    pkt_flows = []                                     # (src, h, vol_bytes) A3
    for group, home in zip(ia_groups, ia_homes):
        members = [act[i] for i in group]
        h = max((ic.hops(home, m) for m in members if m != home), default=0.0)
        for r, tag in _mcast_segs(ic, home, members):
            key = f"{r}/{tag}" if tag else r
            load[key] = load.get(key, 0.0) + ev["in"]
        if h > 0:
            pkt_flows.append((home, h, ev["in"]))
        hops_seen += [ic.hops(home, m) for m in members if m != home]
    for group, home in zip(oa_groups, oa_homes):
        for gi in group:
            m = act[gi]
            if m == home:
                continue
            for r, tag in ic.path_directed(m, home):
                key = f"{r}/{tag}" if tag else r
                load[key] = load.get(key, 0.0) + ev["out"] * width
            pkt_flows.append((m, ic.hops(m, home), ev["out"] * width))
            hops_seen.append(ic.hops(m, home))

    bw = lv.link.bandwidth_words_per_cycle
    busiest = max(load.values(), default=0.0)
    ser0 = busiest / bw * fab.device.cycle_seconds * fab.schedule_slack if bw else 0.0
    comp = compute_seconds(op, len(act), fabric=fab)
    ser, pkt, pess = _packet_bracket(lv, ser0, comp, pkt_flows)
    prop = max(hops_seen) * lv.link.ns_per_hop * 1e-9
    return {"compute_s": comp, "serialization_s": ser, "prop_s": prop,
            "busiest_words": busiest, "packet_term_s": pkt,
            "latency_max_end_s": max(comp, ser) + prop,
            "latency_sum_end_s": comp + ser + prop,
            "latency_pess_s": pess}


def t2_baseline_homes(n_ia: int, n_oa: int,
                      active: Sequence[int] = None):
    """A2-4: Fig 14(b)'s sequential allocation from the first chiplet."""
    act = list(active if active is not None else T2_ACTIVE)
    ia = [act[j % len(act)] for j in range(n_ia)]
    oa = [act[(n_ia + h) % len(act)] for h in range(n_oa)]
    return ia, oa


def t2_greedy_homes(op, die_split, fabric=None, active: Sequence[int] = None):
    """A2-5: iterative greedy, objective per §5.2 / Fig 14(c)-(d)."""
    from scripts import placement as placement_mod
    fab = fabric or simba_fabric()
    ic = ic_mod.build(fab, "die", placement_mod.sequential_fill(fab))
    act = list(active if active is not None else T2_ACTIVE)
    _, ia_groups, oa_groups, _ = _t2_blocks(op, die_split, fab)

    def pick(cost_fn, used):
        pool = [d for d in act if d not in used] or act
        best = min(pool, key=lambda d: (cost_fn(d), d))
        used.add(best)
        return best

    ia_used, ia_homes = set(), []
    for group in ia_groups:
        members = [act[i] for i in group]
        ia_homes.append(pick(lambda d: len(_mcast_segs(ic, d, members)),
                             ia_used))
    oa_used, oa_homes = set(), []
    for group in oa_groups:
        members = [act[i] for i in group]
        oa_homes.append(pick(lambda d: sum(ic.hops(m, d) for m in members),
                             oa_used))
    return ia_homes, oa_homes


def t2_run(fabric=None) -> dict:
    """The full T2 experiment (A2): per layer, freeze the tiling at the
    baseline placement, then grade greedy vs baseline; plus the A2-8
    res4a_branch1 corner-vs-center sub-case under K:32."""
    fab = fabric or simba_fabric()
    layers = {}
    for name in T2_LAYERS:
        op = RESNET50[name]
        scored = []
        for cand in t2_candidate_splits(op):
            _, ia_g, oa_g, _ = _t2_blocks(op, cand, fab)
            ia_h, oa_h = t2_baseline_homes(len(ia_g), len(oa_g))
            r = t2_evaluate(op, cand, ia_h, oa_h, fabric=fab)
            scored.append((r["latency_max_end_s"], sorted(cand.items()), cand))
        scored.sort(key=lambda t: (t[0], t[1]))
        frozen = scored[0][2]
        _, ia_g, oa_g, _ = _t2_blocks(op, frozen, fab)
        ia_h, oa_h = t2_baseline_homes(len(ia_g), len(oa_g))
        base = t2_evaluate(op, frozen, ia_h, oa_h, fabric=fab)
        g_ia, g_oa = t2_greedy_homes(op, frozen, fabric=fab)
        opt = t2_evaluate(op, frozen, g_ia, g_oa, fabric=fab)
        layers[name] = {
            "frozen_split": frozen, "n_ia_blocks": len(ia_g),
            "n_oa_blocks": len(oa_g),
            "baseline": base, "greedy": opt,
            "speedup_max_end": base["latency_max_end_s"] / opt["latency_max_end_s"],
            "speedup_sum_end": base["latency_sum_end_s"] / opt["latency_sum_end_s"],
            "speedup_pess": (base["latency_pess_s"] / opt["latency_pess_s"]
                             if base.get("latency_pess_s") else None),
        }
    # A2-8 sub-case: K:32, single IA home corner vs center, OA local
    op = RESNET50["res4a_branch1"]
    _, ia_g, oa_g, _ = _t2_blocks(op, {"K": 32}, fab)
    oa_local = [T2_ACTIVE[g[0]] for g in oa_g]
    corner = t2_evaluate(op, {"K": 32}, [0], oa_local, fabric=fab)
    center = t2_evaluate(op, {"K": 32}, [T2_CENTER_NODE], oa_local, fabric=fab)
    sub = {"corner": corner, "center": center,
           "corner_over_center": corner["latency_max_end_s"]
                                 / center["latency_max_end_s"],
           "corner_over_center_pess": (corner["latency_pess_s"]
                                       / center["latency_pess_s"]
                                       if corner.get("latency_pess_s") else None)}
    return {"layers": layers, "res4a_corner_vs_center": sub,
            "measured": {"res3a_branch1": 1.160, "res2[a-c]_branch2c": 1.158,
                         "res4a_branch1": 1.046,
                         "res2[a-c]_branch2b": 1.00,
                         "res5[a-c]_branch2b": 1.019,
                         "res4[b-f]_branch2a": 1.00,
                         "res4a_corner_vs_center": 1.05}}


def t2_main():
    res = t2_run()
    out = os.path.join(WS, "analysis", "simba_t2.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=1)
    print("layer                    frozen split         blocks  base_ser  greedy_ser  comp    speedup  measured")
    for name, d in res["layers"].items():
        m = res["measured"].get(name)
        print(f"{name:<24} {str(d['frozen_split']):<20} "
              f"{d['n_ia_blocks']:>2}/{d['n_oa_blocks']:<3} "
              f"{d['baseline']['serialization_s'] * 1e6:8.3f}  "
              f"{d['greedy']['serialization_s'] * 1e6:8.3f}  "
              f"{d['baseline']['compute_s'] * 1e6:6.3f}  "
              f"{d['speedup_max_end']:7.4f}  {m}")
    s = res["res4a_corner_vs_center"]
    print(f"\nres4a K:32 corner/center: {s['corner_over_center']:.4f} "
          f"(measured 1.05); ser corner {s['corner']['serialization_s'] * 1e6:.3f} us, "
          f"center {s['center']['serialization_s'] * 1e6:.3f} us")


if __name__ == "__main__" and os.environ.get("SIMBA_T2"):
    t2_main()


# ======================================================================
# T3 (C47, day 7): the Fig 7 scaling-shape experiment, governed by A4.
# Droppable ordering-class target: chiplet counts 1/4/8/32, per-point
# best tiling under A2-greedy homes, graded at the PESSIMISTIC end
# (A4-3), classes DEGRADE / PLATEAU / SCALE per A4-4.
# ======================================================================

T3_COUNTS = (1, 4, 8, 32)
T3_LAYERS_FIG7 = ["res2[a-c]_branch2b", "res3a_branch1", "res5[a-c]_branch2b"]
T3_MEASURED = {   # pixel-read Fig 7 curves (extracts §C), min in caps
    "res2[a-c]_branch2b": [1.00, 0.783, 0.421, 0.546],   # DEGRADE
    "res3a_branch1":      [1.00, 0.419, 0.256, 0.269],   # PLATEAU
    "res5[a-c]_branch2b": [1.00, 0.276, 0.146, 0.076],   # SCALE
}
T3_EXPECTED_CLASS = {"res2[a-c]_branch2b": "DEGRADE",
                     "res3a_branch1": "PLATEAU",
                     "res5[a-c]_branch2b": "SCALE"}


def t3_seating(n: int) -> List[int]:
    """A4-1: compact blocks as node indices (row-major within block)."""
    if n == 1:
        return [0]
    if n == 4:
        return [0, 1, 6, 7]                            # 2x2
    if n == 8:
        return [0, 1, 2, 3, 6, 7, 8, 9]                # 4x2
    if n == 32:
        return list(T2_ACTIVE)
    raise ValueError(f"no declared seating for n={n}")


def t3_point(op, n: int, fabric=None) -> dict:
    """Best tiling under A2-greedy homes at count n, graded end argmin."""
    fab = fabric or simba_fabric()
    if n == 1:                                          # no die-level flows
        comp = compute_seconds(op, 1, fabric=fab)
        return {"n": 1, "split": {}, "compute_s": comp,
                "latency_max_end_s": comp, "latency_pess_s": comp}
    act = t3_seating(n)
    best = None
    for cand in t2_candidate_splits(op, n_dies=n):
        g_ia, g_oa = t2_greedy_homes(op, cand, fabric=fab, active=act)
        r = t2_evaluate(op, cand, g_ia, g_oa, fabric=fab, active=act)
        key = (r["latency_pess_s"], sorted(cand.items()))
        if best is None or key < best[0]:
            best = (key, cand, r)
    _, cand, r = best
    return {"n": n, "split": cand, **r}


def t3_classify(curve: List[float]) -> str:
    """A4-4 class definitions on the graded curve (indices = T3_COUNTS)."""
    m = min(range(len(curve)), key=lambda i: curve[i])
    if T3_COUNTS[m] == 32:
        return "SCALE"
    if T3_COUNTS[m] in (4, 8):
        return "DEGRADE" if curve[-1] > 1.10 * curve[m] else "PLATEAU"
    return "NONE"                                       # min at 1: no scaling


def t3_run(fabric=None) -> dict:
    fab = fabric or simba_fabric()
    layers = {}
    for name in T3_LAYERS_FIG7:
        op = RESNET50[name]
        pts = [t3_point(op, n, fabric=fab) for n in T3_COUNTS]
        pess = [p["latency_pess_s"] / pts[0]["latency_pess_s"] for p in pts]
        opti = [p["latency_max_end_s"] / pts[0]["latency_max_end_s"]
                for p in pts]
        cls = t3_classify(pess)
        layers[name] = {
            "points": pts, "curve_pess": pess, "curve_opt": opti,
            "class_pess": cls, "class_opt": t3_classify(opti),
            "measured": T3_MEASURED[name],
            "measured_class": T3_EXPECTED_CLASS[name],
            "class_match": cls == T3_EXPECTED_CLASS[name],
        }
    return {"layers": layers,
            "all_classes_match": all(d["class_match"]
                                     for d in layers.values())}


def t3_main():
    res = t3_run()
    for name, d in res["layers"].items():
        print(f"{name}:")
        for p, pe, op_, ms in zip(d["points"], d["curve_pess"],
                                  d["curve_opt"], d["measured"]):
            print(f"  n={p['n']:>2} split={str(p['split']):<28} "
                  f"pess {pe:6.3f}  opt {op_:6.3f}  measured {ms:.3f}")
        print(f"  class: pess {d['class_pess']} / opt {d['class_opt']} "
              f"vs measured {d['measured_class']}  "
              f"{'MATCH' if d['class_match'] else 'MISS'}")
    print(f"\nall classes match: {res['all_classes_match']}")
    out = os.path.join(WS, "analysis", "simba_t3.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=1, default=str)


if __name__ == "__main__" and os.environ.get("SIMBA_T3"):
    t3_main()
