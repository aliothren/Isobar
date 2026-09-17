"""S1 day 2 (C64-b): the evaluator -- score(Pi, mu, caliber), closed form.

Semantic authority: analysis/SEARCH_SPEC.en.md sections 5-6. The four
steps all reuse standing machinery; this module is interface closure.
Every number is closed-form on frozen accounts -- zero mapper.

    score(pi, W, mu, caliber) -> Score(t_opt_s, t_pess_s, e_J, delta,
                                       per_phase, decomp)

  * T_opt ranks; T_pess (the packet-toll pessimistic end) never ranks --
    it ships alongside for the Delta = T_pess/T_opt column (spec section
    5 bracket policy). On non-packet weaves the toll is zero and
    Delta = 1.0 by construction.
  * caliber "single": the pure serial sum (gamma-blind);
    caliber "pipe": segments are stations, the reading is the pipeline
    INTERVAL = max_k t_k (the standing B->infinity semantics).
  * mu: {phase: weight} for the weighted/one-hot modes; the constrained
    mode is the SEARCH's job (rejection, spec section 6) -- score just
    returns per-phase numbers for it.
  * Energy is the lexicographic tie-break channel, reported always.

WORKLOAD BACKENDS (the condition layer owns granularity, day-2
amendment): Workload2p7B -- per-op die-sets (block_chain), accounts from
the frozen mapper-measured scale_2p7b_per_op.json + the elementwise/
digital terms, D2D flows via block_die_flows exactly as A4's script
(wrap excluded). Workload355M -- unit-granularity chain (C13
two-dies-per-layer), D2D via die_to_die_activation + link_occupancy
(identity anchor #2 against the stored b1 rows).

THE HAND-OFF TIME TERM (amended after the 2.7B accounting review): a
2.7B hand-off is MANY concurrent flows -- every producer die ships its
piece to every consumer die at once -- sharing the declared die mesh;
batch-1 serialises layer after layer, NOT the flows inside one
hand-off. The old term collapsed a whole hand-off into one stream over
one link (total words / link rate: a pessimistic upper bound that was
also seat-invariant). The term is now the hand-off's BUSIEST-LINK
volume / link rate: every flow routed on the declared weave, words
accumulated per (link, direction), the same node-flow semantics as the
355M backend's link_occupancy (pinned identical), plus propagation.
When a hand-off is a single flow (one die -> one die, the 355M case)
the definition reduces exactly to words / rate (pinned). Energy is
untouched (flat + distance surplus, per flow, as before). The A4
whole-machine identity anchor is re-established as a RELATION to the
frozen record: stored latency - new latency == the sum over boundaries
of (total words - busiest words) / rate, exactly.
"""
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.crossbar_comm as cc
from scripts import fabric as fabric_mod
from scripts import interconnect as ic
from scripts import llm_workload as lw
from scripts import placement as pm
from scripts import search_space as ss

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
A = os.path.join(WS, "analysis")
PJ_D2D = 10.0                     # GRS band midpoint (per word), standing
NS_PER_HOP_D2D = 20.0


@dataclass(frozen=True)
class Score:
    t_opt_s: float
    t_pess_s: float
    e_J: float
    delta: float                  # T_pess / T_opt (the spec's Delta column)
    per_phase: Dict[str, dict]    # phase -> {t_opt_s, t_pess_s, e_J, decomp}
    caliber: str


# --------------------------------------------------------------- 2.7B class
class Workload2p7B:
    """The A4-class whole model on the frozen per-op account."""

    def __init__(self, fabric=None, die_weave=None):
        self.fab = fabric or fabric_mod.from_yaml(os.path.join(
            WS, "models", "fabric", "mlx300_multidie576.yaml"))
        if die_weave is not None:
            self.fab = _with_die_weave(self.fab, die_weave)
        stored = json.load(open(os.path.join(A, "scale_2p7b_per_op.json")))
        c = stored["config"]
        self.cfg = lw.GptConfig(d_model=c["d_model"], n_heads=c["n_heads"],
                                d_ff=c["d_ff"], n_layers=c["n_layers"],
                                name=c["name"])
        self.S = c["S"]
        self.ops = {ph: {r["name"]: r for r in rows}
                    for ph, rows in stored["phases"].items()}
        self.pl = pm.sequential_fill(self.fab)
        self.die_ic = ic.build(self.fab, "die", self.pl)

    def inventory(self):
        return ss.inventory_from_block_chain(self.cfg, self.S,
                                             self.fab.level("die").per_parent)

    def layer_terms_s(self, phase):
        """(compute, write, elementwise) -- split so the DEVICE-SCALE knob
        (O17 semantics) can shrink the MATRIX part alone: the whole stack
        does not scale, the fixed terms (K/V write, digital unit) stay."""
        elw = sum(lw.elementwise_cost(eo, self.fab.digital)["latency_s"]
                  for eo in lw.block_elementwise_ops(self.cfg, S=self.S,
                                                     phase=phase))
        comp = sum(r["compute_s"] for r in self.ops[phase].values())
        wr = sum(r["write_s"] for r in self.ops[phase].values())
        return comp, wr, elw

    def layer_serial_s(self, phase, device_scale: float = 1.0):
        comp, wr, elw = self.layer_terms_s(phase)
        return comp / device_scale + wr + elw

    def layer_energy_J(self, phase):
        elw = [lw.elementwise_cost(eo, self.fab.digital)
               for eo in lw.block_elementwise_ops(self.cfg, S=self.S,
                                                  phase=phase)]
        return (sum(r["energy_J"] for r in self.ops[phase].values())
                + sum(e["energy_J"] for e in elw))

    def boundaries(self, pi: ss.Pi, phase):
        """Per-boundary dicts (words, hops stats, surplus, into-segment
        index), block_die_flows conventions verbatim, wrap excluded."""
        base = lw.block_chain(self.cfg, self.S, phase, on_chip=True,
                              max_dies=self.fab.level("die").per_parent)
        chain, seating = [], {}
        for li in range(self.cfg.n_layers):
            for e in base:
                name = f"{e['name']}@L{li}"
                chain.append({**e, "name": name})
                seating[name] = list(pi.seat[name])
        flows_by = lw.block_die_flows(chain, seating, self.fab)
        wrap = chain[0]["name"]
        seg_of_block = {}
        for k, (lo, hi) in enumerate(pi.segments()):
            for li in range(lo, hi):
                seg_of_block[li] = k
        out = []
        for e in chain:
            if e["name"] == wrap:
                continue
            fl = flows_by[e["name"]]
            words = sum(f["volume"] * f["width"] for f in fl)
            hops = [self.die_ic.hops(*f["nodes"]) for f in fl]
            li = int(e["name"].rsplit("@L", 1)[1])
            out.append({
                "into": e["name"], "words": words,
                "busiest_words": busiest_link_words(
                    fl, self.die_ic, kappa=getattr(self, "port_ratio", 1.0)),
                "segment": seg_of_block[li],
                "inter_layer": e["name"].startswith(base[0]["name"]),
                "max_hops": max(hops) if hops else 0.0,
                "surplus_J": lw.die_flow_surplus_energy(
                    fl, self.fab, placement=self.pl, pj_per_word=PJ_D2D)})
        return out


# --------------------------------------------------------------- 355M class
class Workload355M:
    """The unit-granularity chain (C13 two-dies-per-layer)."""

    def __init__(self, fabric, d2d_bw_wc: float, die_weave=None):
        import dataclasses as dc
        if die_weave is not None:
            fabric = _with_die_weave(fabric, die_weave)
        base = lw.GptConfig()
        self.n_units = 2 * base.n_layers
        # the unit-granularity hand-off chain: die_to_die_activation walks
        # one hand-off per "layer", so the 48-unit chain is expressed as a
        # 48-"layer" config (the analyze_d2d UCFG convention, verbatim)
        self.cfg = lw.GptConfig(d_model=base.d_model, n_heads=base.n_heads,
                                d_ff=base.d_ff, n_layers=self.n_units,
                                name="units48")
        levels = [dc.replace(l, link=dc.replace(
            l.link, bandwidth_words_per_cycle=d2d_bw_wc))
            if l.name == "die" else l for l in fabric.levels]
        self.fab = dc.replace(fabric, name="w355m", levels=levels).validate()
        self.pl = pm.sequential_fill(self.fab)

    def inventory(self):
        return ss.inventory_units(self.n_units)

    def assignment_of(self, pi: ss.Pi):
        return [pi.seat[f"unit{u}"][0] for u in range(self.n_units)]

    def d2d(self, pi: ss.Pi, phase):
        d = lw.die_to_die_activation(self.cfg, 512, phase, fabric=self.fab,
                                     assignment=self.assignment_of(pi))
        occ = cc.link_occupancy(d["flows"], self.fab,
                                self.fab.device.cycle_seconds, self.pl)
        return d, occ


def _one_boundary_flows(prev_e, e, prod_slots, cons_slots, fab):
    """ONE boundary's node-to-node flows -- the block_die_flows convention
    verbatim (piece/width by the producer's split; every consumer die
    receives the whole tensor), without the modulo-wrap validation a
    two-entry mini-chain would trip. The incremental == full pin is the
    standing guard that this stays identical to the full path."""
    psum = getattr(fab, "psum_word_bytes", 2.0)
    lv = fab.level("die")
    if prev_e["out_words"] != e["in_words"]:
        raise ValueError(f"{prev_e['name']} -> {e['name']}: words mismatch")
    if prev_e["split"] == "C":
        piece, width = float(prev_e["out_words"]), psum
    else:
        piece, width = prev_e["out_words"] / len(prod_slots), 1.0
    flows = []
    for a in prod_slots:
        for b in cons_slots:
            if a == b:
                continue
            flows.append({"level": lv.link.name, "level_name": "die",
                          "nodes": (a, b), "src": f"{prev_e['name']}@{a}",
                          "dst": f"{e['name']}@{b}", "volume": float(piece),
                          "width": width, "distance": 0.0})
    return flows


def resource_loads(flows, icl, ports: bool = True, kappa: float = 1.0):
    """The per-(resource, direction) load map behind the hand-off term:
    links by icl.path_directed, plus each die's ONE injection and ONE
    ejection port. `kappa` = C_port / C_link (S8): port loads are
    expressed in LINK-TIME units, i.e. divided by kappa, so kappa = 1
    is the standing 'ports at the link rate' model and kappa -> inf
    recovers the wire-only term. Returned so tie-breaking features can
    be read off the same map the maximum comes from."""
    load = {}
    split = icl.duplex
    for f in flows:
        vol = f["volume"] * float(f.get("width", 1.0))
        if vol <= 0:
            continue
        a, b = f["nodes"]
        for r, tag in icl.path_directed(a, b):
            key = (r, tag if (split and tag) else "")
            load[key] = load.get(key, 0.0) + vol
        if ports:
            load[("port", a, "inj")] = load.get(("port", a, "inj"), 0.0) + vol / kappa
            load[("port", b, "ej")] = load.get(("port", b, "ej"), 0.0) + vol / kappa
    return load


def busiest_link_words(flows, icl, ports: bool = True, kappa: float = 1.0) -> float:
    """The hand-off's BUSIEST-RESOURCE volume over links AND node ports.

    Every producer->consumer flow is routed on the declared die weave
    (icl.path_directed) and its volume x width is accumulated per
    (resource, direction) exactly as link_occupancy's node-to-node
    branch does (pinned identical). PORTS (added after the B7 external
    adjudication, finding F-B7): each die also has ONE INJECTION and
    ONE EJECTION port -- at the link rate when kappa = 1 (the declared
    model, the same assumption the BookSim bridge makes), at kappa x
    the link rate otherwise (S8 port sweep; port load / kappa) -- so a
    flow also loads its source's injection port and its destination's
    ejection port. The hand-off time is set by the busiest of ALL these
    resources, in link-time units.

    Why ports were added: counting links but not ports is loose exactly
    where flows stack on an endpoint instead of a wire, which is the
    DISPERSED geometry -- the very family our own ladder calls best.
    B7 measured the bias (a dispersed hand-off's busiest link carried
    816 flits while its busiest injection port carried 1088), so the
    omission was biased in favour of our own conclusion. `ports=False`
    reproduces the wire-only term for the B7 comparison rows.

    Degeneration, pinned: when a hand-off is a single flow the port
    and every link on its path carry the same volume, so the maximum
    is unchanged -- the 355M backend and any one-die-to-one-die
    hand-off read exactly as before (and for any kappa >= 1)."""
    load = resource_loads(flows, icl, ports, kappa)
    return max(load.values()) if load else 0.0


def _with_die_weave(fab, die_weave):
    """The condition-enumeration knob (spec section 3, S1 day-3 amendment):
    swap the DIE-level weave (topology, params) on a fabric. The weave is
    a CONDITION -- it rides the workload constructor, and score() itself
    stays weave-free; this is S6's E3 entry point, added before the
    interface freeze."""
    import dataclasses as dc
    topology, params = die_weave
    levels = [dc.replace(l, link=dc.replace(l.link, topology=topology,
                                            params=dict(params)))
              if l.name == "die" else l for l in fab.levels]
    return dc.replace(fab, name=f"{fab.name}-{topology}",
                      levels=levels).validate()


# ------------------------------------------------------------------- score
def _packet_toll_s(fab, boundaries):
    """The pessimistic end's per-hop toll on packet-declared die links
    (zero on every production weave -- the packet fields are unset)."""
    lk = fab.level("die").link
    if lk.packet_payload_bytes is None:
        return 0.0
    t_hop = lk.ns_per_hop * 1e-9
    return sum((-(-b["words"] // lk.packet_payload_bytes))
               * b["max_hops"] * t_hop for b in boundaries)


def _assemble(pi, W, bs_by_phase, mu, caliber, d2d_gbps, device_scale):
    per_phase = {}
    for phase in mu:
        bs = bs_by_phase[phase]
        wps = d2d_gbps * 1e9                       # 8-bit words per second
        prop_s = sum(b["max_hops"] for b in bs) * NS_PER_HOP_D2D * 1e-9
        layer_s = W.layer_serial_s(phase, device_scale)
        layer_J = W.layer_energy_J(phase)
        n_seg = len(pi.segments())
        seg_layers = [hi - lo for lo, hi in pi.segments()]
        seg_bnd_s = [0.0] * n_seg
        for b in bs:
            seg_bnd_s[b["segment"]] += b["busiest_words"] / wps
        d2d_s = sum(seg_bnd_s)
        t_single = W.n_layers() * layer_s + d2d_s + prop_s
        stage_s = [seg_layers[k] * layer_s + seg_bnd_s[k]
                   for k in range(n_seg)]
        t_pipe = max(stage_s) if stage_s else 0.0
        t_opt = t_single if caliber == "single" else t_pipe
        toll = _packet_toll_s(W.fab, bs)
        e = (W.n_layers() * layer_J
             + sum(b["words"] for b in bs) * PJ_D2D * 1e-12
             + sum(b["surplus_J"] for b in bs))
        per_phase[phase] = {
            "t_opt_s": t_opt, "t_pess_s": t_opt + toll, "e_J": e,
            "decomp": {"layers_s": W.n_layers() * layer_s,
                       "d2d_serial_s": d2d_s, "propagation_s": prop_s,
                       "stage_s": stage_s, "t_single_s": t_single,
                       "t_pipe_interval_s": t_pipe,
                       "d2d_words": sum(b["words"] for b in bs),
                       "d2d_busiest_words": sum(b["busiest_words"]
                                                for b in bs),
                       "d2d_flat_J": sum(b["words"] for b in bs)
                       * PJ_D2D * 1e-12,
                       "d2d_surplus_J": sum(b["surplus_J"] for b in bs)}}
    t_opt = sum(mu[p] * per_phase[p]["t_opt_s"] for p in mu)
    t_pess = sum(mu[p] * per_phase[p]["t_pess_s"] for p in mu)
    e = sum(mu[p] * per_phase[p]["e_J"] for p in mu)
    return Score(t_opt_s=t_opt, t_pess_s=t_pess, e_J=e,
                 delta=(t_pess / t_opt if t_opt else 1.0),
                 per_phase=per_phase, caliber=caliber)


def score(pi: ss.Pi, W, mu: Optional[Dict[str, float]] = None,
          caliber: str = "single", d2d_gbps: float = 12.5,
          device_scale: float = 1.0) -> Score:
    mu = mu or {"prefill": 1.0}
    if caliber not in ("single", "pipe"):
        raise ValueError(f"caliber must be single or pipe, got {caliber}")
    ok, why = ss.legal(pi, W.fab, W.inventory())
    if not ok:
        raise ValueError(f"illegal Pi: {why}")
    bs = {phase: W.boundaries(pi, phase) for phase in mu}
    return _assemble(pi, W, bs, mu, caliber, d2d_gbps, device_scale)


class ScoreSession:
    """The incremental-evaluation hook (spec section 8): holds Pi and the
    per-phase boundary cache; a seat move recomputes ONLY the affected
    boundaries (the moved set's own in-boundary and its successor's).
    incremental == full is a pinned identity, not an assumption."""

    def __init__(self, pi: ss.Pi, W, mu=None, caliber="single",
                 d2d_gbps=12.5, device_scale=1.0):
        self.W, self.mu = W, (mu or {"prefill": 1.0})
        self.caliber, self.d2d_gbps = caliber, d2d_gbps
        self.device_scale = device_scale
        self.pi = pi
        self._chains = {ph: self._chain(ph) for ph in self.mu}
        self.bs = {ph: W.boundaries(pi, ph) for ph in self.mu}

    def _chain(self, phase):
        base = lw.block_chain(self.W.cfg, self.W.S, phase, on_chip=True,
                              max_dies=self.W.fab.level("die").per_parent)
        names = [f"{e['name']}@L{li}" for li in range(self.W.cfg.n_layers)
                 for e in base]
        entries = {f"{e['name']}@L{li}": e for li in range(self.W.cfg.n_layers)
                   for e in base}
        return names, entries

    def update(self, new_seats: Dict[str, tuple]) -> Score:
        """Apply seat changes; recompute only the affected boundaries."""
        seat = dict(self.pi.seat)
        seat.update({k: tuple(v) for k, v in new_seats.items()})
        import dataclasses as dc
        self.pi = dc.replace(self.pi, seat=seat)
        for ph in self.mu:
            names, entries = self._chains[ph]
            idx = {n: i for i, n in enumerate(names)}
            affected = set()
            for k in new_seats:
                affected.add(k)                          # its own in-boundary
                affected.add(names[(idx[k] + 1) % len(names)])   # successor's
            seg_of = {}
            for si, (lo, hi) in enumerate(self.pi.segments()):
                for li in range(lo, hi):
                    seg_of[li] = si
            by_name = {b["into"]: b for b in self.bs[ph]}
            wrap = names[0]
            for name in affected:
                if name == wrap:
                    continue                              # excluded boundary
                prev = names[idx[name] - 1]
                fl = _one_boundary_flows(
                    entries[prev], entries[name],
                    self.pi.seat[prev], self.pi.seat[name], self.W.fab)
                words = sum(f["volume"] * f["width"] for f in fl)
                hops = [self.W.die_ic.hops(*f["nodes"]) for f in fl]
                li = int(name.rsplit("@L", 1)[1])
                by_name[name] = {
                    "into": name, "words": words, "segment": seg_of[li],
                    "busiest_words": busiest_link_words(
                        fl, self.W.die_ic,
                        kappa=getattr(self.W, "port_ratio", 1.0)),
                    "inter_layer": by_name[name]["inter_layer"],
                    "max_hops": max(hops) if hops else 0.0,
                    "surplus_J": lw.die_flow_surplus_energy(
                        fl, self.W.fab, placement=self.W.pl,
                        pj_per_word=PJ_D2D)}
            self.bs[ph] = [by_name[n] for n in names if n != wrap]
        return _assemble(self.pi, self.W, self.bs, self.mu, self.caliber,
                         self.d2d_gbps, self.device_scale)


# the 2.7B backend exposes n_layers uniformly
def _n_layers_2p7b(self):
    return self.cfg.n_layers


Workload2p7B.n_layers = _n_layers_2p7b
