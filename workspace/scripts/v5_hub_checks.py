"""Hand-calculable checks of the hub resource model (request section 6,
batch 4): aggregation into the unit, distribution out of it, a shared die
port, and hub saturation, on a 3 x 3 mesh with the unit at the centre
(node 4). Each case states the expected service time by hand and compares
it with load_components and the hand-off time rule
max(link / B, dport / (kappa B), hub / C_hub).

    python3 scripts/v5_hub_checks.py
"""
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import interconnect as ic, placement as pm, search_eval as se, v3_sweep as v3   # noqa: E402

fab = v3.make_fabric((3, 3), "mesh", "xy")
pl = pm.sequential_fill(fab)
icl = ic.build(fab, "die", pl)
HUB = 4                      # centre of the 3 x 3 grid
B, kappa, C = 0.4e9, 2.0, 12.5e9


def flow(a, b, v, w=1.0):
    return {"level": "d", "level_name": "die", "nodes": (a, b), "src": str(a), "dst": str(b), "volume": v, "width": w, "distance": 0.0}


def t_of(flows):
    link, dport, hub = se.load_components(flows, icl, kappa=kappa, hub_nodes=(HUB,))
    return max(link / B, dport / B, hub / C), (link, dport, hub)


cases = []
v = 1e6
# 1. aggregation: the four edge-adjacent dies (1, 3, 5, 7) each send v words to the unit: every flow is one hop on its own link,
#    the unit's ejection port carries 4v; expected max(v/B, v/(kappa B), 4v/C)
t, comp = t_of([flow(n, HUB, v) for n in (1, 3, 5, 7)])
cases.append(("aggregation 4 -> unit", t, max(v / B, v / (kappa * B), 4 * v / C), comp))
# 2. distribution: the unit sends v to each of the four: the injection port carries 4v
t, comp = t_of([flow(HUB, n, v) for n in (1, 3, 5, 7)])
cases.append(("distribution unit -> 4", t, max(v / B, v / (kappa * B), 4 * v / C), comp))
# 3. shared die port: two producers (0 and 2) into die 1: die 1's ejection port carries 2v at kappa B; each link one hop
t, comp = t_of([flow(0, 1, v), flow(2, 1, v)])
cases.append(("shared die ejection port", t, max(v / B, 2 * v / (kappa * B)), comp))
# 4. hub saturation: 8 producers each v into the unit with a hub interface of C' = 1.0e9 (below the mesh rate x 8): the hub term binds
Cs = 1.0e9
link, dport, hub = se.load_components([flow(n, HUB, v) for n in (0, 1, 2, 3, 5, 6, 7, 8)], icl, kappa=kappa, hub_nodes=(HUB,))
t = max(link / B, dport / B, hub / Cs)
# corners route XY through an edge node onto the centre: the vertical links into the centre carry 3v (two corners + the edge die) -> 3v/B vs 8v/C'
cases.append(("hub saturation (C_hub 1 GB/s, 8 producers)", t, max(3 * v / B, v / (kappa * B), 8 * v / Cs), (link, dport, hub)))
ok = True
for name, got, exp, comp in cases:
    good = abs(got - exp) <= 1e-12 * max(1.0, exp)
    ok &= good
    print(f"{'PASS' if good else 'FAIL'} {name}: model {got*1e3:.4f} ms, by hand {exp*1e3:.4f} ms; components link {comp[0]:.0f} dport/kappa {comp[1]:.0f} hub {comp[2]:.0f} words")
print("all hand checks pass" if ok else "a hand check FAILED")
