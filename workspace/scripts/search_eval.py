"""The closed-form evaluator: score() prices a mapping Pi of a workload W
from its stored per-operator account (no mapper run).

    score(pi, W, mu, caliber, d2d_gbps, device_scale)
        -> Score(t_opt_s, t_pess_s, e_J, delta, per_phase, caliber)

  * Latency T = R + H. R is the layer time times the layer count: CIM
    compute (divided by device_scale) + CIM writes + digital element-wise
    operators, plus the digital unit's time when the attention is
    offloaded. H is the communication time
        H = sum over hand-offs j of [P_j + max over resources r of V_jr / C_r].
    All flows of a hand-off are in flight at once (every producer die
    sends its piece to every consumer die); batch-1 execution serialises
    the hand-offs, not the flows inside one. Each flow is routed on the
    die-level network and its words are accumulated per (resource,
    direction) over directed links (capacity B = d2d_gbps), die injection
    and ejection ports (kappa B, kappa = W.port_ratio) and digital-unit
    hub ports (C_hub); P_j = the hand-off's largest hop count x
    NS_PER_HOP_D2D.
  * caliber "single": the serial sum over layers and hand-offs
    (independent of the cuts gamma); "pipe": the segments of gamma are
    pipeline stages, t_k = the segment's layer times + its hand-off
    service times, and the reading is the interval max_k t_k.
  * mu = {phase: weight}: the score is the weighted sum of the per-phase
    numbers, which per_phase reports with their decomposition.
  * T_opt is the latency above; T_pess adds a per-packet hop toll on die
    links that declare a packet size. No shipped fabric does, so
    T_pess = T_opt and delta = T_pess / T_opt = 1.
  * e_J, the dynamic energy, sums the account energies, PJ_D2D per
    die-to-die word and each flow's distance surplus; it does not enter
    the latency.

Workload2p7B (and its subclass experiment.AccountWorkload) is the workload
backend: the per-operator die-set chain of llm_workload.block_chain
repeated over the layers, with the die flows of
llm_workload.block_die_flows (the wrap hand-off into the first entry is
excluded). ScoreSession re-prices only the hand-offs a seat move touches
and returns the same Score as a full score().
"""
import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import fabric as fabric_mod
from scripts import interconnect as ic
from scripts import llm_workload as lw
from scripts import placement as pm
from scripts import paths
from scripts import search_space as ss

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PJ_D2D = 10.0                     # pJ per 8-bit word-hop: midpoint of Simba's GRS package-link band (Zimmer et al., JSSC 2020)
NS_PER_HOP_D2D = 20.0


@dataclass(frozen=True)
class Score:
    t_opt_s: float
    t_pess_s: float
    e_J: float
    delta: float                  # T_pess / T_opt
    per_phase: Dict[str, dict]    # phase -> {t_opt_s, t_pess_s, e_J, decomp}
    caliber: str


# --------------------------------------------------------------- 2.7B class
class Workload2p7B:
    """A transformer stack priced from a stored per-operator account. By
    default the 2.7B-class reference account (paths.REFERENCE_ACCOUNT) on
    the 576-die package fabric; `die_weave` = (topology, params) replaces
    the die-level network."""

    def __init__(self, fabric=None, die_weave=None):
        self.fab = fabric or fabric_mod.from_yaml(os.path.join(
            WS, "models", "fabric", "mlx300_multidie576.yaml"))
        if die_weave is not None:
            self.fab = _with_die_weave(self.fab, die_weave)
        stored = json.load(open(paths.REFERENCE_ACCOUNT))
        c = stored["config"]
        self.cfg = lw.GptConfig(d_model=c["d_model"], n_heads=c["n_heads"], d_ff=c["d_ff"],
                                n_layers=c["n_layers"], name=c["name"],
                                **{k: c[k] for k in ("head_dim", "n_kv_heads", "ffn_gated", "activation") if k in c})
        self.S = c["S"]
        self.ops = {ph: {r["name"]: r for r in rows}
                    for ph, rows in stored["phases"].items()}
        self.pl = pm.sequential_fill(self.fab)
        self.die_ic = ic.build(self.fab, "die", self.pl)

    # the tiler's split-dimension preference; the tiling variants (experiment.TILINGS) override it
    tiling_dims = ("M", "C")
    # attention offload (scripts/offload.OffloadConfig) or None = the attention die with K/V in ReRAM
    offload = None

    @property
    def on_chip(self):
        return self.offload is None

    def hub_nodes(self):
        return () if self.offload is None else tuple(self.offload.hubs)

    def usable_slots(self):
        reserved = self.offload.reserved_slots() if self.offload is not None else set()
        return [i for i in range(self.fab.level("die").per_parent) if i not in reserved]

    def inventory(self):
        return ss.inventory_from_block_chain(self.cfg, self.S,
                                             self.fab.level("die").per_parent,
                                             dims=self.tiling_dims, on_chip=self.on_chip)

    def _static_ops(self, phase):
        """The account rows the dies execute: every operator on chip; the
        static operators only when the attention is offloaded."""
        rows = self.ops[phase].values()
        return rows if self.on_chip else [r for r in rows if r["kind"] != "dynamic"]

    def _elementwise(self, phase):
        ops = lw.block_elementwise_ops(self.cfg, S=self.S, phase=phase)
        return ops if self.on_chip else [eo for eo in ops if eo.name not in lw.ATTENTION_ELEMENTWISE]

    def unit_terms(self, phase):
        """The offloaded attention's per-layer unit cost (None on chip). Head
        mode: every unit works its head share in parallel, so the layer's
        unit time is one unit's share."""
        if self.on_chip:
            return None
        from scripts import offload as offload_mod
        off = self.offload
        if off.split == "head":
            return offload_mod.unit_layer_cost(self.cfg, self.S, phase, off.unit, heads=self.cfg.n_heads // off.K, kv_heads=self.cfg.kv_heads // off.K)
        return offload_mod.unit_layer_cost(self.cfg, self.S, phase, off.unit)

    def chain_entries(self, phase):
        """The block chain under the workload's attention setting, the
        attention entry carrying the head-split layout when offloaded over
        several units."""
        base = lw.block_chain(self.cfg, self.S, phase, on_chip=self.on_chip,
                              max_dies=self.fab.level("die").per_parent,
                              dims=getattr(self, "tiling_dims", ("M", "C")))
        if self.offload is not None and self.offload.split == "head":
            base = [head_mode_entry(e, self.cfg, self.offload.K) if e["name"] == lw.ATTENTION_DIE else e for e in base]
        return base

    def layer_terms_s(self, phase):
        """(compute, write, elementwise) of one layer, kept apart so that
        `device_scale` speeds up the CIM compute term alone while the
        fixed terms (writes, digital unit, K/V) stay. Offloaded: compute
        covers the static operators only, the write slot also carries the
        unit's time (compute + K/V memory), and the element-wise terms
        exclude the softmax (it runs on the unit)."""
        elw = sum(lw.elementwise_cost(eo, self.fab.digital)["latency_s"] for eo in self._elementwise(phase))
        comp = sum(r["compute_s"] for r in self._static_ops(phase))
        wr = sum(r["write_s"] for r in self._static_ops(phase))
        u = self.unit_terms(phase)
        if u is not None:
            wr += u["unit_s"]
        return comp, wr, elw

    def layer_breakdown_s(self, phase):
        """Named per-layer terms for the record."""
        u = self.unit_terms(phase)
        return {"cim_compute_s": sum(r["compute_s"] for r in self._static_ops(phase)),
                "cim_write_s": sum(r["write_s"] for r in self._static_ops(phase)),
                "digital_elementwise_s": sum(lw.elementwise_cost(eo, self.fab.digital)["latency_s"] for eo in self._elementwise(phase)),
                "unit_compute_s": u["compute_s"] if u else 0.0, "unit_kv_s": u["kv_s"] if u else 0.0}

    def layer_serial_s(self, phase, device_scale: float = 1.0):
        comp, wr, elw = self.layer_terms_s(phase)
        return comp / device_scale + wr + elw

    def layer_energy_J(self, phase):
        elw = [lw.elementwise_cost(eo, self.fab.digital) for eo in self._elementwise(phase)]
        u = self.unit_terms(phase)
        return (sum(r["energy_J"] for r in self._static_ops(phase))
                + sum(e["energy_J"] for e in elw) + (u["energy_J"] if u else 0.0))

    def boundaries(self, pi: ss.Pi, phase):
        """Per-hand-off dicts over the whole chain (words, busiest link /
        die-port / hub-port loads, max hops, energy surplus, receiving
        segment), with the flow conventions of block_die_flows; the wrap
        hand-off into the first entry is excluded."""
        base = self.chain_entries(phase)
        chain, seating = [], {}
        for li in range(self.cfg.n_layers):
            for e in base:
                name = f"{e['name']}@L{li}"
                chain.append({**e, "name": name})
                seating[name] = seats_of(self, pi, name)
        flows_by = lw.block_die_flows(chain, seating, self.fab)
        hubs = self.hub_nodes()
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
            link, dport, hub = load_components(fl, self.die_ic, kappa=getattr(self, "port_ratio", 1.0), hub_nodes=hubs)
            out.append({
                "into": e["name"], "words": words,
                "busiest_words": max(link, dport),        # links and die ports, link-time units (the hub port is priced at C_hub in _assemble)
                "link_words": link, "dport_words": dport, "hub_words": hub,
                "segment": seg_of_block[li],
                "inter_layer": e["name"].startswith(base[0]["name"]),
                "max_hops": max(hops) if hops else 0.0,
                "surplus_J": lw.die_flow_surplus_energy(
                    fl, self.fab, placement=self.pl, pj_per_word=PJ_D2D)})
        return out


def _one_boundary_flows(prev_e, e, prod_slots, cons_slots, fab):
    """The node-to-node flows of one hand-off: llm_workload.boundary_flows,
    the convention block_die_flows applies to the full chain, called
    directly so that no two-entry chain (with its wrap hand-off) has to be
    built. Keeps the incremental path identical to the full one."""
    return lw.boundary_flows(prev_e, e, list(prod_slots), list(cons_slots), fab)


def seats_of(W, pi, name):
    """The nodes of a chain entry: the seated die-set, or the unit node of
    the layer when the attention is offloaded (the entry is not in pi)."""
    if name in pi.seat:
        return list(pi.seat[name])
    off = getattr(W, "offload", None)
    if off is None:
        raise KeyError(name)
    li = int(name.rsplit("@L", 1)[1])
    return off.unit_nodes(li)


def head_mode_entry(e, cfg, K):
    """The attention chain entry under the head split: K consumer 'units',
    each taking complete head groups of the QKV output's columns (Q block,
    K block, V block per unit), and producing its share of the attention
    output (split 'H' on the way out)."""
    from scripts import offload as offload_mod
    dh = cfg.dh; H, Hkv = cfg.n_heads, cfg.kv_heads
    groups = offload_mod.head_groups(cfg, K)
    cols = []
    for g in groups:
        q0, q1 = g["q_heads"]; k0, k1 = g["kv_heads"]
        cols.append([(q0 * dh, q1 * dh), (H * dh + k0 * dh, H * dh + k1 * dh), ((H + Hkv) * dh + k0 * dh, (H + Hkv) * dh + k1 * dh)])
    return {**e, "split": "H", "in_cols": (H + 2 * Hkv) * dh, "unit_cols": cols, "n_units": K}


def resource_loads(flows, icl, ports: bool = True, kappa: float = 1.0, hub_ratio=None, hub_nodes=()):
    """The per-(resource, direction) load map behind the hand-off term:
    links by icl.path_directed, plus each node's one injection and one
    ejection port. `kappa` = C_port / C_link: port loads are expressed in
    link-time units, i.e. divided by kappa, so kappa = 1 puts the ports at
    the link rate and kappa -> inf recovers the wire-only term; a node in
    `hub_nodes` uses `hub_ratio` instead when one is given. Returned whole
    so that callers can read the binding resource off the same map the
    maximum comes from."""
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
            ka = hub_ratio if (hub_ratio is not None and a in hub_nodes) else kappa     # a unit node's interface has its own capacity C_hub
            kb = hub_ratio if (hub_ratio is not None and b in hub_nodes) else kappa
            load[("port", a, "inj")] = load.get(("port", a, "inj"), 0.0) + vol / ka
            load[("port", b, "ej")] = load.get(("port", b, "ej"), 0.0) + vol / kb
    return load


def load_components(flows, icl, kappa: float = 1.0, hub_nodes=()):
    """(busiest link words, busiest die-port words / kappa, busiest hub-port
    words) of one hand-off, so a service time can be formed under any
    (B_mesh, C_hub): max(link / B, die-port words / (kappa B), hub / C_hub)."""
    load = resource_loads(flows, icl, ports=True, kappa=1.0)
    link = max((v for k, v in load.items() if k[0] != "port"), default=0.0)
    dport = max((v for k, v in load.items() if k[0] == "port" and k[1] not in hub_nodes), default=0.0) / kappa
    hub = max((v for k, v in load.items() if k[0] == "port" and k[1] in hub_nodes), default=0.0)
    return link, dport, hub


def busiest_link_words(flows, icl, ports: bool = True, kappa: float = 1.0, hub_ratio=None, hub_nodes=()) -> float:
    """The hand-off's busiest-resource volume over links and node ports.

    Every producer->consumer flow is routed on the die-level network
    (icl.path_directed) and its volume x width is accumulated per
    (resource, direction), as in link_occupancy's node-to-node branch.
    Each die also has one injection and one ejection port, at kappa x
    the link rate (kappa = 1: the link rate, as in the BookSim bridge;
    port load / kappa), so a flow also loads its source's injection port
    and its destination's ejection port. The hand-off time is set by the
    busiest of all these resources, in link-time units.

    Counting links alone underestimates hand-offs whose flows converge on
    an endpoint rather than on a wire, as in dispersed seatings;
    `ports=False` gives that wire-only term.

    When a hand-off is a single flow, its ports and every link on its
    path carry the same volume, so for any kappa >= 1 the result is the
    flow's volume (words / rate, as for one stream)."""
    load = resource_loads(flows, icl, ports, kappa, hub_ratio, hub_nodes)
    return max(load.values()) if load else 0.0


def _with_die_weave(fab, die_weave):
    """The fabric with its die-level network replaced: die_weave =
    (topology, params). The network is a fixed condition of the workload,
    set at construction; score() never changes it."""
    import dataclasses as dc
    topology, params = die_weave
    levels = [dc.replace(l, link=dc.replace(l.link, topology=topology,
                                            params=dict(params)))
              if l.name == "die" else l for l in fab.levels]
    return dc.replace(fab, name=f"{fab.name}-{topology}",
                      levels=levels).validate()


# ------------------------------------------------------------------- score
def _packet_toll_s(fab, boundaries):
    """The per-packet hop toll T_pess adds on die links that declare a
    packet size: per hand-off, ceil(words / payload bytes) x max hops x
    the per-hop time. Zero on every shipped fabric (packet fields unset)."""
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
        off = getattr(W, "offload", None)
        hub_wps = off.unit["link_bandwidth_gbps"] * 1e9 if off is not None else None
        busiest_words = 0.0
        for b in bs:
            t_b = b["busiest_words"] / wps
            if hub_wps is not None and b.get("hub_words", 0.0) > 0:
                t_b = max(t_b, b["hub_words"] / hub_wps)         # the unit's interface under its own capacity C_hub
            seg_bnd_s[b["segment"]] += t_b
            busiest_words += t_b * wps                            # the hand-off's load expressed at the mesh link rate (A/B = H at this B)
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
                       "d2d_busiest_words": busiest_words,
                       "hub_words_sum": sum(b.get("hub_words", 0.0) for b in bs),
                       "link_words_sum": sum(b.get("link_words", b["busiest_words"]) for b in bs),
                       "layer_breakdown_s": (W.layer_breakdown_s(phase) if hasattr(W, "layer_breakdown_s") else None),
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
    """Incremental evaluation: holds the committed Pi and the per-phase
    hand-off cache; update() recomputes only the affected hand-offs (each
    moved set's incoming hand-off and its successor's) and re-assembles a
    Score equal to a full score() of the same Pi."""

    def __init__(self, pi: ss.Pi, W, mu=None, caliber="single",
                 d2d_gbps=12.5, device_scale=1.0):
        self.W, self.mu = W, (mu or {"prefill": 1.0})
        self.caliber, self.d2d_gbps = caliber, d2d_gbps
        self.device_scale = device_scale
        self.pi = pi
        self._chains = {ph: self._chain(ph) for ph in self.mu}
        self.bs = {ph: W.boundaries(pi, ph) for ph in self.mu}

    def _chain(self, phase):
        base = self.W.chain_entries(phase) if hasattr(self.W, "chain_entries") else lw.block_chain(
            self.W.cfg, self.W.S, phase, on_chip=True, max_dies=self.W.fab.level("die").per_parent, dims=getattr(self.W, "tiling_dims", ("M", "C")))
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
                affected.add(k)                          # its incoming hand-off
                affected.add(names[(idx[k] + 1) % len(names)])   # successor's
            hubs = self.W.hub_nodes() if hasattr(self.W, "hub_nodes") else ()
            seg_of = {}
            for si, (lo, hi) in enumerate(self.pi.segments()):
                for li in range(lo, hi):
                    seg_of[li] = si
            by_name = {b["into"]: b for b in self.bs[ph]}
            wrap = names[0]
            for name in affected:
                if name == wrap:
                    continue                              # the wrap hand-off is excluded
                prev = names[idx[name] - 1]
                fl = _one_boundary_flows(
                    entries[prev], entries[name],
                    seats_of(self.W, self.pi, prev), seats_of(self.W, self.pi, name), self.W.fab)
                words = sum(f["volume"] * f["width"] for f in fl)
                hops = [self.W.die_ic.hops(*f["nodes"]) for f in fl]
                li = int(name.rsplit("@L", 1)[1])
                link, dport, hub = load_components(fl, self.W.die_ic, kappa=getattr(self.W, "port_ratio", 1.0), hub_nodes=hubs)
                by_name[name] = {
                    "into": name, "words": words, "segment": seg_of[li],
                    "busiest_words": max(link, dport), "link_words": link, "dport_words": dport, "hub_words": hub,
                    "inter_layer": by_name[name]["inter_layer"],
                    "max_hops": max(hops) if hops else 0.0,
                    "surplus_J": lw.die_flow_surplus_energy(
                        fl, self.W.fab, placement=self.W.pl,
                        pj_per_word=PJ_D2D)}
            self.bs[ph] = [by_name[n] for n in names if n != wrap]
        return _assemble(self.pi, self.W, self.bs, self.mu, self.caliber,
                         self.d2d_gbps, self.device_scale)


# the layer count as a method, W.n_layers()
def _n_layers_2p7b(self):
    return self.cfg.n_layers


Workload2p7B.n_layers = _n_layers_2p7b
