"""Group 49 (cont.) -- S1 day 2: score() and the TRIPLE IDENTITY ANCHORS.

Anchor 1: score(A4-Pi, prefill, single) reproduces a4_full_model.json's
whole-machine column at every bandwidth anchor, and its energy, to 1e-9
-- the evaluator IS the standing analysis, interface-closed.
Anchor 2: the 355M backend reproduces the stored b1 ordering rows
(avg hops / busiest / surplus / wire-ms) for all three orderings.
Anchor 3: the per-op rows are the frozen accounts verbatim (spot), and
the layer serial/energy equal A4's stored values.
Plus: the pipe caliber's structural identities and the Delta column
(== 1.0 on packet-free weaves, by construction)."""
import json
import os

from _util import approx

from scripts import fabric, llm_workload as lw
from scripts import search_eval as se
from scripts import search_space as ss

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
A4 = json.load(open(os.path.join(WS, "analysis", "a4_full_model.json")))


def _W():
    return se.Workload2p7B()


def _pi():
    return ss.pi_from_a4_payload(os.path.join(WS, "analysis",
                                              "a4_full_model.json"))


def test_anchor1_a4_whole_machine_identity():
    """Anchor 1, RE-ESTABLISHED as a RELATION to the frozen record (the
    2.7B hand-off accounting review): energy, words, surplus and
    propagation reproduce a4_full_model.json exactly as before; the
    latency now carries the busiest-link hand-off term, and the stored
    (one-stream-per-hand-off) latency minus the new latency equals the
    sum over boundaries of (total words - busiest words) / link rate --
    the old account is recoverable from the new one to 1e-9."""
    W, pi = _W(), _pi()
    bs = W.boundaries(pi, "prefill")
    for bw in (12.5, 2.0, 0.4, 0.1):
        sc = se.score(pi, W, mu={"prefill": 1.0}, caliber="single",
                      d2d_gbps=bw)
        wps = bw * 1e9
        old_minus_new = sum((b["words"] - b["busiest_words"]) / wps
                            for b in bs)
        approx(sc.t_opt_s + old_minus_new,
               A4["latency_s"]["whole"][f"{bw}GBps"], 1e-9)
        assert old_minus_new >= 0.0            # the old term was the bound
        approx(sc.e_J, A4["energy_J"]["whole"], 1e-9)
        approx(sc.delta, 1.0, 1e-12)          # packet-free weave
        d = sc.per_phase["prefill"]["decomp"]
        approx(d["d2d_words"], A4["d2d"]["total_words"], 1e-9)
        approx(d["d2d_flat_J"], A4["d2d"]["flat_J"], 1e-9)
        approx(d["d2d_surplus_J"], A4["d2d"]["surplus_J"], 1e-9)
        approx(d["propagation_s"], A4["d2d"]["propagation_s"], 1e-9)


# ------------------- the hand-off term's own pins (accounting review)
def _slot_index_by_xy(W):
    from scripts import placement as pm
    xy = pm.sequential_fill(W.fab).slots["die"]
    return {(int(x), int(y)): i for i, (x, y) in enumerate(xy)}


def _flows(W, prod_xy, cons_xy, V=1.0e6):
    idx = _slot_index_by_xy(W)
    prev_e = {"name": "p", "out_words": V, "split": "R"}
    e = {"name": "c", "in_words": V}
    return se._one_boundary_flows(prev_e, e, [idx[p] for p in prod_xy],
                                  [idx[c] for c in cons_xy], W.fab)


def test_handoff_hand_example_no_sharing():
    """Two producers on the same column, one consumer between them: the
    two flows run in opposite directions on disjoint links, so the
    busiest link carries ONE piece = V/2 (total words = V). Routing-order
    independent (pure-y moves)."""
    W = _W()
    fl = _flows(W, [(0, 0), (0, 2)], [(0, 1)])
    V = 1.0e6
    assert abs(sum(f["volume"] * f["width"] for f in fl) - V) < 1e-12
    assert abs(se.busiest_link_words(fl, W.die_ic, ports=False)
               - V / 2) < 1e-12
    # with ports the consumer's EJECTION port takes both halves: V
    assert abs(se.busiest_link_words(fl, W.die_ic) - V) < 1e-12


def test_handoff_hand_example_sharing():
    """Two producers on one row feeding one consumer further along it:
    both pieces share the last two links in the same direction, so the
    busiest link carries V/2 + V/2 = V = total words."""
    W = _W()
    fl = _flows(W, [(0, 0), (1, 0)], [(3, 0)])
    V = 1.0e6
    assert abs(se.busiest_link_words(fl, W.die_ic, ports=False) - V) < 1e-12
    assert abs(se.busiest_link_words(fl, W.die_ic) - V) < 1e-12  # port ties


def test_handoff_single_flow_degenerates_to_words_over_rate():
    """One die -> one die (the 355M case): exactly one flow, every link on
    its path carries the whole hand-off, busiest == total words."""
    W = _W()
    for prod, cons in (((0, 0), (5, 7)), ((3, 3), (3, 4)), ((9, 2), (0, 0))):
        fl = _flows(W, [prod], [cons])
        words = sum(f["volume"] * f["width"] for f in fl)
        assert se.busiest_link_words(fl, W.die_ic, ports=False) == words
        assert se.busiest_link_words(fl, W.die_ic) == words


def test_handoff_port_degenerates_on_single_flow():
    """F-B7 port term, pin 1: with ONE flow the source port, the
    destination port and every link on the path carry the same volume,
    so the port-aware term equals the wire-only one exactly -- the
    355M backend and any one-die-to-one-die hand-off cannot move."""
    W = _W()
    for prod, cons in (((0, 0), (5, 7)), ((3, 3), (3, 4)), ((9, 2), (0, 0))):
        fl = _flows(W, [prod], [cons])
        with_p = se.busiest_link_words(fl, W.die_ic, ports=True)
        without = se.busiest_link_words(fl, W.die_ic, ports=False)
        assert with_p == without
        assert with_p == sum(f["volume"] * f["width"] for f in fl)


def test_handoff_port_binds_on_dispersed_geometry():
    """F-B7 port term, pin 2: the case B7 measured -- a hand-off whose
    flows spread over the mesh stacks on the ENDPOINT, not on any wire,
    so the port-aware term is strictly larger; and it equals the
    producer's own injected volume (one port, whole share)."""
    W = _W()
    prod = [(0, 0), (11, 1), (2, 9), (9, 11)]
    cons = [(11, 0), (0, 5), (6, 6), (5, 11)]
    fl = _flows(W, prod, cons)
    with_p = se.busiest_link_words(fl, W.die_ic, ports=True)
    without = se.busiest_link_words(fl, W.die_ic, ports=False)
    assert with_p > without
    V = 1.0e6
    approx(with_p, V / len(prod) * len(cons), 1e-9)   # one producer's share


def test_handoff_accumulator_equals_link_occupancy():
    """The accumulator is the 355M backend's own semantics: on a real
    2.7B boundary's flows the WIRE-ONLY term equals link_occupancy's
    bottleneck volume on the same weave (nominal bandwidth set only so
    that link_occupancy routes; volume is bandwidth-independent).
    link_occupancy itself models links only, so this pin is stated on
    ports=False -- the port term is the declared EXTENSION (F-B7), and
    the pin below shows it never moves a single-flow reading."""
    import dataclasses as dc
    import scripts.crossbar_comm as cc
    W, pi = _W(), _pi()
    base = lw.block_chain(W.cfg, W.S, "prefill", on_chip=True,
                          max_dies=W.fab.level("die").per_parent)
    chain = [{**e, "name": f"{e['name']}@L{li}"} for li in range(2)
             for e in base]
    seating = {c["name"]: list(pi.seat[c["name"]]) for c in chain}
    flows_by = lw.block_die_flows(chain, seating, W.fab)
    levels = [dc.replace(l, link=dc.replace(l.link,
                                            bandwidth_words_per_cycle=1.0))
              if l.name == "die" else l for l in W.fab.levels]
    fab_route = dc.replace(W.fab, name="route", levels=levels).validate()
    checked = 0
    for name, fl in flows_by.items():
        if not fl:
            continue
        occ = cc.link_occupancy(fl, fab_route, fab_route.device.cycle_seconds,
                                W.pl)
        approx(se.busiest_link_words(fl, W.die_ic, ports=False),
               occ["bottleneck"]["volume"], 1e-12)
        checked += 1
    assert checked >= 6


def test_anchor2_355m_b1_identity():
    stored = json.load(open(os.path.join(WS, "analysis", "d2d_impact.json")))
    from scripts import analyze_d2d as d2d
    base = fabric.from_yaml(d2d.MULTI)
    W = se.Workload355M(d2d.with_link(base, "mesh",
                                      {"routing": "xy", "hub": "center"},
                                      stored["example_bw"]),
                        stored["example_bw"])
    words = stored["S"] * lw.GptConfig().d_model      # one boundary's words
    for row, (label, asg) in zip(stored["assignments"],
                                 d2d.assignments(W.fab)):
        assert row["assignment"] == label
        pi = ss.Pi(n_blocks=W.n_units, cuts=(W.n_units,),
                   seat={f"unit{u}": (asg[u],) for u in range(W.n_units)})
        ok, why = ss.legal(pi, W.fab, W.inventory())
        assert ok, why
        d, occ = W.d2d(pi, "prefill")
        approx(d["avg_die_hops"], row["avg_hops"], 1e-9)
        approx(d["energy_J"] * 1e6, row["surplus_uJ"], 1e-6)
        approx(occ["bottleneck"]["volume"] / words, row["busiest_x"], 1e-9)
        approx(occ["serialization_s"] * 1e3, row["wire_ms_at_point"], 1e-9)


def test_anchor3_per_op_rows_are_the_frozen_account():
    W = _W()
    stored = json.load(open(os.path.join(WS, "analysis",
                                         "scale_2p7b_per_op.json")))
    for ph in ("prefill", "decode"):
        for r in stored["phases"][ph]:
            assert W.ops[ph][r["name"]] == r
    approx(W.layer_serial_s("prefill"), A4["layer_serial_s"], 1e-12)
    approx(W.layer_energy_J("prefill"), A4["layer_energy_J"], 1e-12)


def test_pipe_caliber_structure():
    """gamma feeds the pipe caliber only: 16 stages of 2 layers; the
    interval = the max stage; single is gamma-blind (same t_opt for any
    cuts); internal identities hold."""
    import dataclasses
    W, pi = _W(), _pi()
    sc = se.score(pi, W, caliber="pipe", d2d_gbps=12.5)
    d = sc.per_phase["prefill"]["decomp"]
    assert len(d["stage_s"]) == 16
    approx(sc.t_opt_s, max(d["stage_s"]), 1e-12)
    approx(d["t_single_s"],
           d["layers_s"] + d["d2d_serial_s"] + d["propagation_s"], 1e-12)
    lo = min(d["stage_s"])
    assert max(d["stage_s"]) / lo < 1.2       # near-uniform stages (2 layers)
    single_a = se.score(pi, W, caliber="single", d2d_gbps=12.5).t_opt_s
    single_b = se.score(dataclasses.replace(pi, cuts=(32,)), W,
                        caliber="single", d2d_gbps=12.5).t_opt_s
    approx(single_a, single_b, 1e-12)


def test_decode_phase_and_weighted_mu():
    W, pi = _W(), _pi()
    sd = se.score(pi, W, mu={"decode": 1.0}, d2d_gbps=12.5)
    assert sd.t_opt_s > 0 and sd.e_J > 0
    both = se.score(pi, W, mu={"prefill": 0.5, "decode": 0.5},
                    d2d_gbps=12.5)
    sp = se.score(pi, W, mu={"prefill": 1.0}, d2d_gbps=12.5)
    approx(both.t_opt_s, 0.5 * sp.t_opt_s + 0.5 * sd.t_opt_s, 1e-12)
    stored = json.load(open(os.path.join(WS, "analysis",
                                         "scale_2p7b_per_op.json")))
    dec = sum(r["compute_s"] + r["write_s"]
              for r in stored["phases"]["decode"])
    assert W.layer_serial_s("decode") > dec   # elementwise terms included


# ------------------------------------------------- day 3: hooks + freeze
def test_incremental_equals_full():
    """The section-8 identity pin: a ScoreSession applying random seat
    swaps must equal a fresh full score after every step -- incremental
    is an optimization, never a semantics."""
    import random

    import dataclasses
    W, pi = _W(), _pi()
    sess = se.ScoreSession(pi, W, mu={"prefill": 1.0}, caliber="pipe",
                           d2d_gbps=2.0)
    rng = random.Random(11)
    names = list(pi.seat)
    for _ in range(4):
        a, b = rng.sample(names, 2)
        if len(pi.seat[a]) != len(pi.seat[b]):
            continue
        new = {a: pi.seat[b], b: pi.seat[a]}
        inc = sess.update(new)
        pi = dataclasses.replace(pi, seat={**pi.seat, **{k: tuple(v) for k, v in new.items()}})
        full = se.score(pi, W, mu={"prefill": 1.0}, caliber="pipe",
                        d2d_gbps=2.0)
        approx(inc.t_opt_s, full.t_opt_s, 1e-12)
        approx(inc.e_J, full.e_J, 1e-12)
        approx(max(inc.per_phase["prefill"]["decomp"]["stage_s"]),
               max(full.per_phase["prefill"]["decomp"]["stage_s"]), 1e-12)


def test_device_scale_shrinks_the_matrix_part_only():
    """O17 semantics: the knob divides the COMPUTE term alone; write and
    elementwise (the fixed terms) stay; scale=1 is the identity; energy
    never moves with device speed."""
    W, pi = _W(), _pi()
    base = se.score(pi, W, d2d_gbps=12.5)
    fast = se.score(pi, W, d2d_gbps=12.5, device_scale=10.0)
    comp, wr, elw = W.layer_terms_s("prefill")
    approx(base.t_opt_s - fast.t_opt_s, 32 * comp * (1 - 1 / 10.0), 1e-9)
    approx(fast.e_J, base.e_J, 1e-12)
    approx(W.layer_serial_s("prefill", 1.0),
           comp + wr + elw, 1e-12)


def test_die_weave_knob_is_the_e3_entry():
    """The condition knob added before the freeze: the workload
    constructor swaps the die weave; score() stays weave-free. On the
    355M b1 chain under ring, die_to_die_activation reads hops() --
    the PHYSICAL caliber, folded x2 -- so the C60-pinned ordering
    STRUCTURE appears at twice the count values (sequential rows =
    native 1 crossing = 2.0 physical; snake 1.745 -> 3.49): the
    ordering-role swap survives the caliber."""
    from scripts import analyze_d2d as d2d
    base = fabric.from_yaml(d2d.MULTI)
    W = se.Workload355M(base, 256.0, die_weave=("ring", {}))
    asgs = dict(d2d.assignments(W.fab))
    for label, want in (("sequential rows", 2.0), ("snake", 3.49)):
        pi = ss.Pi(n_blocks=W.n_units, cuts=(W.n_units,),
                   seat={f"unit{u}": (asgs[label][u],)
                         for u in range(W.n_units)})
        d, _ = W.d2d(pi, "prefill")
        approx(d["avg_die_hops"], want, 2e-3)
    W2 = se.Workload2p7B(die_weave=("mesh", {"routing": "xy",
                                             "hub": "center"}))
    assert W2.fab.level("die").link.topology == "mesh"


def test_incremental_equals_full_on_ring_weave():
    """The post-closeout review pin (permanent, like every identity pin in
    this group): day 3's only bug was a wrap edge case, and the ring
    weave is built ENTIRELY on wrap -- so the incremental path meets the
    non-default weave here, before SA ever hammers it (S6 runs
    non-default weaves). Same identity, same tolerance."""
    import random

    import dataclasses
    W = se.Workload2p7B(die_weave=("ring", {}))
    pi = _pi()
    sess = se.ScoreSession(pi, W, mu={"prefill": 1.0}, caliber="pipe",
                           d2d_gbps=2.0)
    rng = random.Random(23)
    names = list(pi.seat)
    for _ in range(4):
        a, b = rng.sample(names, 2)
        if len(pi.seat[a]) != len(pi.seat[b]):
            continue
        new = {a: pi.seat[b], b: pi.seat[a]}
        inc = sess.update(new)
        pi = dataclasses.replace(
            pi, seat={**pi.seat, **{k: tuple(v) for k, v in new.items()}})
        full = se.score(pi, W, mu={"prefill": 1.0}, caliber="pipe",
                        d2d_gbps=2.0)
        approx(inc.t_opt_s, full.t_opt_s, 1e-12)
        approx(inc.e_J, full.e_J, 1e-12)


# ------------------------------------------------- S2 day 4: the baselines
def test_baseline_registry_all_legal_both_workloads():
    """Spec section 9: seven generators, one signature, every output
    legal on BOTH workload classes; the registry is closed (exactly
    these names)."""
    from scripts import analyze_d2d as d2d
    from scripts import search_baselines as sb
    assert tuple(sb.REGISTRY) == sb.NAMES and len(sb.NAMES) == 7
    W2 = _W()
    W3 = se.Workload355M(fabric.from_yaml(d2d.MULTI), 256.0)
    for W in (W2, W3):
        for name in sb.NAMES:
            pi = sb.generate(name, W, seed=3)      # generate() asserts legal
            assert set(pi.seat) == set(W.inventory())
    try:
        sb.generate("clever_new_heuristic", W2)
    except ValueError as e:
        assert "closed" in str(e)
    else:
        raise AssertionError("the closed registry accepted a new name")


def test_baseline_determinism_and_degenerations():
    """Seeded runs are bit-identical; random varies with the seed;
    sequential DEGENERATES to the A4 payload map on the 2.7B class (the
    mapper's default-seat by-product, pinned)."""
    from scripts import search_baselines as sb
    W = _W()
    for name in sb.NAMES:
        assert sb.generate(name, W, seed=7) == sb.generate(name, W, seed=7)
    assert sb.generate("random", W, seed=1) != sb.generate("random", W, seed=2)
    seq = sb.generate("sequential", W)
    a4 = _pi()
    assert seq.seat == a4.seat                     # the pinned degeneration
    assert sb.generate("snake", W).seat != seq.seat


# --------------------------- S2 day 5 item 0: baseline faithfulness (A, B)
def _both_W():
    from scripts import analyze_d2d as d2d
    return (_W(), se.Workload355M(fabric.from_yaml(d2d.MULTI), 256.0))


def test_faith_A1_nmap_original_single_sweep_replay():
    """A1 (permanent, C64-c check D revision): the NMAP original's
    refinement is a FIXED single O(U^2) pairwise sweep with per-row
    best-commit (mappingwithsinglepath(), excerpt in
    analysis/baseline_traces.md) -- NOT run-to-convergence. The pin is
    an independent replay of that exact structure: starting from the
    constructive seating, one sweep coded here from the pseudocode must
    land on generate()'s output seat for seat."""
    from scripts import search_baselines as sb
    for W in _both_W():
        pi = sb.generate("nmap_greedy", W)
        names, inv, words, _ = sb._chain_info(W)
        xy = sb._slots_xy(W)
        seat = dict(sb._nmap_construct(W))       # phase 1-2 output
        for i, a in enumerate(names):            # phase 3, per pseudocode
            bestcommcost = sb._nmap_cost(seat, names, words, xy)
            bestmapping = None
            for b in names[i + 1:]:              # for j = i+1 to |U|
                if inv[a] != inv[b]:             # declared adaptation
                    continue
                ptemp = dict(seat)
                ptemp[a], ptemp[b] = ptemp[b], ptemp[a]
                commcost = sb._nmap_cost(ptemp, names, words, xy)
                if commcost < bestcommcost - 1e-12:
                    bestcommcost, bestmapping = commcost, ptemp
            if bestmapping is not None:          # Bestmapping -> Placed
                seat = bestmapping
        assert seat == pi.seat


def test_clustered_355m_degenerates_to_snake():
    """Closeout item 4 (permanent): on the 355M 1-die-per-unit class the
    rectangle tiling degenerates to 1x1 rectangles walked in snake
    order = the snake baseline itself; the two seatings must be EQUAL
    seat for seat (spec section 9 [AMENDED 8] degeneration clause)."""
    from scripts import search_baselines as sb
    _, W = _both_W()
    assert sb.generate("clustered", W).seat == sb.generate("snake", W).seat


def test_faith_A2_least_manhattan_greedy_replay():
    """A2 (permanent): SIAM's rule is stepwise greedy, so it is REPLAYED
    step by step independently and every pick must align with the code."""
    from scripts import search_baselines as sb
    for W in _both_W():
        pi = sb.generate("least_manhattan", W)
        names, inv, _, _ = sb._chain_info(W)
        xy = sb._slots_xy(W)
        free = set(range(len(xy)))
        prev_c = xy[0]
        for n in names:
            want = tuple(sorted(free,
                                key=lambda i: (sb._manh(xy[i], prev_c), i)
                                )[:inv[n]])
            assert pi.seat[n] == want, (n, pi.seat[n], want)
            free -= set(want)
            prev_c = sb._centroid(xy, want)


def test_faith_A3_clustered_regions_connected():
    """A3 (permanent -- the check that CAUGHT the original growth bug:
    4 of 32 stages disconnected, one shattered to a single slot; the
    implementation was replaced by literal rectangle tiling): every
    stage's region is grid-connected, on both workload classes."""
    from scripts import placement as pm
    from scripts import search_baselines as sb
    for W in _both_W():
        pi = sb.generate("clustered", W)
        xy = pm.sequential_fill(W.fab).slots["die"]
        names, _, _, layer = sb._chain_info(W)
        for li in set(layer.values()):
            blob = [s for n in names if layer[n] == li
                    for s in pi.seat[n]]
            seen, stack, bs = {blob[0]}, [blob[0]], set(blob)
            while stack:
                c = stack.pop()
                for o in bs - seen:
                    if sb._manh(xy[c], xy[o]) == 1:
                        seen.add(o)
                        stack.append(o)
            assert seen == bs, f"stage {li} disconnected"


def test_faith_A4_heaviest_first_replay():
    """A4 (permanent): the placement order is STRICTLY descending
    boundary weight, and each step's picks are exactly the
    least-stretch feasible slots at that moment -- replayed
    independently."""
    from scripts import search_baselines as sb
    for W in _both_W():
        pi = sb.generate("heaviest_first", W)
        names, inv, words, _ = sb._chain_info(W)
        xy = sb._slots_xy(W)
        bounds = sorted(zip(names[:-1], names[1:]),
                        key=lambda pc: -words[pc[1]])
        weights = [words[c] for _, c in bounds]
        assert weights == sorted(weights, reverse=True)
        free, seat = set(range(len(xy))), {}
        cx = (max(x for x, _ in xy) / 2, max(y for _, y in xy) / 2)

        def place(n, anchor):
            picks = tuple(sorted(free, key=lambda i: (sb._manh(xy[i],
                                                               anchor), i)
                                 )[:inv[n]])
            assert pi.seat[n] == picks, (n, pi.seat[n], picks)
            seat[n] = picks
            free.difference_update(picks)

        for prev, cur in bounds:
            if prev not in seat and cur not in seat:
                place(prev, cx)
                place(cur, sb._centroid(xy, seat[prev]))
            elif prev in seat and cur not in seat:
                place(cur, sb._centroid(xy, seat[prev]))
            elif cur in seat and prev not in seat:
                place(prev, sb._centroid(xy, seat[cur]))


def test_faith_B_evaluator_parameter_blindness():
    """B (permanent): bandwidth, device_scale, caliber and mu are
    EVALUATOR-side; no baseline's output Pi may move with any of them
    (geometry -- fabric, die_weave -- is the allowed dependency). The
    355M constructor takes a bandwidth, so it is exercised at two
    values; the generators never see caliber/mu/device_scale by
    construction and the fixed-W outputs pin that."""
    from scripts import analyze_d2d as d2d
    from scripts import search_baselines as sb
    W_lo = se.Workload355M(fabric.from_yaml(d2d.MULTI), 64.0)
    W_hi = se.Workload355M(fabric.from_yaml(d2d.MULTI), 16384.0)
    for name in sb.NAMES:
        assert (sb.generate(name, W_lo, seed=5)
                == sb.generate(name, W_hi, seed=5)), name
