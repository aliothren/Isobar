"""The silicon seating reference of Fig. 3(a): Simba (Shao et al., MICRO'19,
section 4.6, Fig. 9), the ResNet-50 layer res4a_branch1 on four chiplets with
the tiling fixed and only the seating varied. The five seatings are the
figure's: expanding squares anchored at (0, 0) with side 1 to 5 on the 6x6
package mesh. Closed form on models/fabric/simba.yaml: no mapper, no
simulator.

Occupancy: node-to-node flows, with the input slices multicast (each shared
route segment charged once) and the partial sums as distinct data at the
partial-sum width. Resource service lower bound = max(compute, busiest
segment volume / link bandwidth) + longest-path propagation at 20 ns per
hop; protocol estimate = compute + serialization + round-serialized packets
(17 flits of 128 B). Each series is normalised to its adjacent-seating value
and compared with the measured execution times read from the figure.

    python3 scripts/run_simba_reference.py -> results/reference/simba_seating.json
"""
import json
import os
import sys
from typing import Dict, List, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import interconnect as ic_mod                       # noqa: E402
from scripts import paths                                         # noqa: E402
from scripts.simba_workload import (RESNET50, compute_seconds,    # noqa: E402
                                    conv_structure, simba_fabric)
from scripts.traffic import IN_DISTINCT, OUT_REDUCED              # noqa: E402

# the five seatings of Fig. 9 as (x, y) = (col, row) on the 6x6 package mesh, anchor first
SEATINGS: List[List[Tuple[int, int]]] = [
    [(0, 0), (0, k), (k, 0), (k, k)] for k in range(1, 6)
]
# the figure's bars (execution time relative to the adjacent seating), read to +-0.01
MEASURED = [1.000, 1.359, 1.739, 2.122, 2.530]
LAYER = "res4a_branch1"


def _die_nodes(fabric, seating: Sequence[Tuple[int, int]]) -> List[int]:
    """Seat coordinates -> node indices of the row-major die slot table."""
    mx, _ = fabric.level("die").mesh
    return [y * mx + x for (x, y) in seating]


def _coord_groups(split, keep) -> List[List[int]]:
    """Instance indices grouped by the kept dims' coordinates (the last
    listed dim varies fastest)."""
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
    """Packet terms: the serialization with the packet wire overhead, and
    the protocol estimate. pkt_flows = [(src, h, vol_bytes)]; per source the
    packet rounds add up (one manager issues serially), across sources the
    maximum is taken (parallel managers); the protocol estimate composes
    compute, serialization and packet rounds by sum (its first round holds
    the head's propagation)."""
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


def candidate_splits(op) -> List[Dict[str, int]]:
    """The tilings over four dies: power-of-two factorizations over {K, C},
    plus P / Q where exact (R = S = 1) and divisible."""
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


def evaluate_seating(op, die_split: Dict[str, int],
                     seating: Sequence[Tuple[int, int]], fabric=None) -> dict:
    """Latency terms of `op` under `die_split` on one seating."""
    from scripts import placement as placement_mod
    fab = fabric or simba_fabric()
    lv = fab.level("die")
    pl = placement_mod.sequential_fill(fab)
    ic = ic_mod.build(fab, "die", pl)
    nodes = _die_nodes(fab, seating)
    src = nodes[0]                                     # input activations live at the anchor

    ts = conv_structure(op, die_split=die_split, fabric=fab)
    split = ts.splits[0]
    assert split.level == "die" and split.fanout == len(nodes)
    ev = ts.edge_volumes()["die"]

    load: Dict[str, float] = {}
    pkt_flows = []                                     # (src, h, vol_bytes)
    # input multicast: instances sharing every input-distinct coordinate get
    # the same slice; its route segments are charged once (Simba's multicast
    # is physical: one-hot addressing, cut-through)
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
    # partial sums: reduction-group members -> the group's first member,
    # distinct data at the partial-sum width; pure K splits produce none
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


def run(fabric=None) -> dict:
    """The tiling is chosen once at the adjacent seating (lowest resource
    bound, deterministic tie-break) and kept; the five seatings are then
    evaluated with it."""
    fab = fabric or simba_fabric()
    op = RESNET50[LAYER]
    scored = []
    for cand in candidate_splits(op):
        r = evaluate_seating(op, cand, SEATINGS[0], fabric=fab)
        scored.append((r["latency_max_end_s"], sorted(cand.items()), cand, r))
    scored.sort(key=lambda t: (t[0], t[1]))            # deterministic tie-break
    frozen = scored[0][2]

    rows = []
    for seating, measured in zip(SEATINGS, MEASURED):
        r = evaluate_seating(op, frozen, seating, fabric=fab)
        rows.append({"seating": seating, "measured_norm": measured, **r})
    base = rows[0]
    for r in rows:
        r["ratio_max_end"] = r["latency_max_end_s"] / base["latency_max_end_s"]
        r["ratio_sum_end"] = r["latency_sum_end_s"] / base["latency_sum_end_s"]
    for r in rows:
        if rows[0].get("latency_pess_s"):
            r["ratio_pess"] = r["latency_pess_s"] / rows[0]["latency_pess_s"]
    lat = [r["latency_max_end_s"] for r in rows]
    return {"layer": LAYER, "frozen_split": frozen,
            "enumeration": [{"split": c, "latency_max_end_s": s_} for s_, _, c, _ in scored],
            "rows": rows,
            "bound_strictly_increasing": all(a < b for a, b in zip(lat, lat[1:])),
            "ratio_far_bound": rows[-1]["ratio_max_end"],
            "ratio_far_protocol": rows[-1].get("ratio_pess")}


def main():
    res = run()
    out = os.path.join(paths.ensure(paths.REFERENCE), os.path.basename(paths.SIMBA_SEATING))
    with open(out, "w") as f:
        json.dump(res, f, indent=1)
    print(f"tiling over the four dies: {res['frozen_split']}")
    print("enumeration (resource bound at the adjacent seating):")
    for e in res["enumeration"]:
        print(f"  {e['split']}: {e['latency_max_end_s'] * 1e6:.3f} us")
    print("\n   seating                          measured  bound          ratio      ser_us  comp_us  prop_ns")
    for i, r in enumerate(res["rows"], 1):
        print(f"  {i}  {str(r['seating']):<32} {r['measured_norm']:.3f}  "
              f"{r['latency_max_end_s'] * 1e6:10.4f} us  {r['ratio_max_end']:.6f}  "
              f"{r['serialization_s'] * 1e6:7.3f}  {r['compute_s'] * 1e6:7.3f}  "
              f"{r['prop_s'] * 1e9:6.1f}")
    print(f"\nfarthest / adjacent: bound {res['ratio_far_bound']:.4f}, protocol {res['ratio_far_protocol']:.4f}, "
          f"measured {MEASURED[-1]:.3f} -> {out}")


if __name__ == "__main__":
    main()
