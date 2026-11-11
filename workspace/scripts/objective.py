"""The incremental objective of the deployment search and the hand-off flow
listing shared by the experiment engine, the BookSim libraries and the
exporters.

Objective wraps a search_eval.ScoreSession: a candidate deployment is
diffed against the committed seats and only the hand-offs the move touches
are re-priced, so one annealer step costs a fraction of a full evaluation.
handoff_flows lists, in chain order, the node-to-node flows of every
hand-off of a deployment (the wrap boundary excluded, as in the evaluator);
handoff_row summarises one hand-off's routed loads.
"""
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import llm_workload as lw                # noqa: E402
from scripts import search_eval as se                 # noqa: E402

DEFAULT_FABRIC = os.path.join(WS, "models", "fabric", "mlx300_multidie576.yaml")   # the package fabric of the experiments


def handoff_flows(W, pi, phase):
    """[(into-set name, flows)] for every hand-off of the chain, in chain
    order, the wrap boundary excluded (the evaluator's convention)."""
    base = W.chain_entries(phase) if hasattr(W, "chain_entries") else lw.block_chain(
        W.cfg, W.S, phase, on_chip=True, max_dies=W.fab.level("die").per_parent, dims=getattr(W, "tiling_dims", ("M", "C")))
    names = [f"{e['name']}@L{li}" for li in range(W.cfg.n_layers) for e in base]
    entries = {f"{e['name']}@L{li}": e for li in range(W.cfg.n_layers) for e in base}
    out = []
    for i in range(1, len(names)):
        prev, name = names[i - 1], names[i]
        out.append((name, se._one_boundary_flows(entries[prev], entries[name],
                                                 se.seats_of(W, pi, prev), se.seats_of(W, pi, name), W.fab)))
    return out


def handoff_row(name, flows, W, kappa):
    loads = se.resource_loads(flows, W.die_ic, ports=True, kappa=kappa)
    if not loads:
        return {"into": name, "words": 0.0, "busiest_words": 0.0, "binding": "none",
                "busiest_resource": None, "max_hops": 0, "n_flows": 0}
    key, a = max(loads.items(), key=lambda kv: kv[1])
    wire = max((v for k, v in loads.items() if k[0] != "port"), default=0.0)
    ports = max((v for k, v in loads.items() if k[0] == "port"), default=0.0)
    eps = 1e-9 * a
    if abs(a - ports) < eps and abs(a - wire) < eps:
        binding = "port=link"
    elif abs(a - ports) < eps:
        binding = "port"
    elif abs(a - wire) < eps:
        binding = "link"
    else:
        binding = "mixed"
    hops = max((W.die_ic.hops(*f["nodes"]) for f in flows), default=0)
    return {"into": name, "words": sum(f["volume"] * f["width"] for f in flows),
            "busiest_words": a, "binding": binding,
            "busiest_resource": [str(x) for x in key],
            "port_floor_words": ports, "wire_only_words": wire,
            "max_hops": hops, "n_flows": len(flows)}


class Objective:
    """Incremental objective on a ScoreSession: the requested Pi is diffed
    against the committed seats and only the touched hand-offs are
    re-priced. column "t" returns the latency, "e" the dynamic energy."""

    def __init__(self, W, pi0, mu, caliber, bw, device_scale, column="t"):
        self.W, self.column = W, column
        self.sess = se.ScoreSession(pi0, W, mu=mu, caliber=caliber,
                                    d2d_gbps=bw, device_scale=device_scale)
        self.calls = 0

    def __call__(self, pi):
        self.calls += 1
        delta = {n: tuple(v) for n, v in pi.seat.items()
                 if tuple(v) != tuple(self.sess.pi.seat[n])}
        sc = (self.sess.update(delta) if delta else
              se._assemble(self.sess.pi, self.W, self.sess.bs, self.sess.mu,
                           self.sess.caliber, self.sess.d2d_gbps,
                           self.sess.device_scale))
        return sc.t_opt_s if self.column == "t" else sc.e_J
