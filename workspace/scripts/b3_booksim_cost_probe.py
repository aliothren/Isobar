"""Item 3 groundwork: how long does BookSim take on one boundary of the
SHRUNK complete instance (2.7B per-op structure, 2 layers, 34 of 36
dies on a 6x6 mesh) at candidate volume scales? Decides the scale the
item-3 protocol pre-registers. Not a result."""
import dataclasses as dc
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import booksim_bridge as bb
from scripts import llm_workload as lw
from scripts import search_baselines as sb
from scripts import search_eval as se


def shrunk_workload():
    W0 = se.Workload2p7B()
    levels = [dc.replace(l, per_parent=36, mesh=(6, 6)) if l.name == "die" else l
              for l in W0.fab.levels]
    W = se.Workload2p7B(fabric=dc.replace(W0.fab, name="shrunk36",
                                          levels=levels).validate())
    W.cfg = dc.replace(W.cfg, n_layers=2, name="2p7b_2L")
    return W


def boundary_flows(W, pi, phase="prefill"):
    """[(into, [(src, dst, words)])] per boundary, the evaluator's own
    flow construction (Workload2p7B.boundaries), wrap excluded."""
    base = lw.block_chain(W.cfg, W.S, phase, on_chip=True,
                          max_dies=W.fab.level("die").per_parent)
    chain, seating = [], {}
    for li in range(W.cfg.n_layers):
        for e in base:
            name = f"{e['name']}@L{li}"
            chain.append({**e, "name": name})
            seating[name] = list(pi.seat[name])
    flows_by = lw.block_die_flows(chain, seating, W.fab)
    wrap = chain[0]["name"]
    out = []
    for e in chain:
        if e["name"] == wrap:
            continue
        fl = [(f["nodes"][0], f["nodes"][1], f["volume"] * f["width"])
              for f in flows_by[e["name"]]]
        out.append((e["name"], fl))
    return out


def main():
    W = shrunk_workload()
    pi = sb.generate("random", W, seed=0)
    bfs = boundary_flows(W, pi)
    print("boundaries:", [(n, len(fl), round(sum(w for _, _, w in fl) / 1e6, 2))
                          for n, fl in bfs])
    name, fl = max(bfs, key=lambda x: sum(w for _, _, w in x[1]))
    for scale in (1 / 256, 1 / 64, 1 / 16):
        pk = [(s, d, bb.packets_for(w * scale)) for s, d, w in fl if w > 0]
        n = sum(p for _, _, p in pk)
        t = time.perf_counter()
        r = bb.run_batch(pk, k=6)
        dt = time.perf_counter() - t
        print(f"  {name}: scale 1/{int(1/scale)} -> {n} packets, BookSim "
              f"{r['cycles']} cycles, wall {dt:.1f} s")


if __name__ == "__main__":
    main()
