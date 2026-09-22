"""Paper figure set v2 (review notes v2, 2026-09-19).

Changes against v1: Fig. 5's mechanism instance is a CONTROLLED 4x4 die
mesh carrying the same 25-flow ffn hand-off (5 producer dies, 5 consumer
dies, 6 empty slots), re-placed, re-routed and re-scored in the evaluator's
own flow and load code; the objective ablation is a dot plot from zero;
Fig. 4's attributions and Fig. 6's statistics and wording are corrected;
Fig. 3's titles state what each panel validates and its rho is recomputed
from the candidate set drawn; Fig. 2 carries a real routing fragment from
the new instance. Formal captions go to captions.md, development notes to
figure_index.md, never into a figure.

Nothing outside the run directory is written; v1 is untouched.

    python3 scripts/plot_dac2027_v2.py --run-id 20260921_v2
"""
import argparse
import json
import math
import os
import random
import sys

os.environ.setdefault("ISOBAR_KAPPA", "2")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["svg.fonttype"] = "none"
matplotlib.rcParams["axes.linewidth"] = 0.7
matplotlib.rcParams["font.size"] = 8
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle

from scripts import plot_dac2027_v1 as V1          # utilities and the Fig. 1 panels
from scripts import search_eval as se

A = se.A
COL_WIDTH, PAGE_WIDTH = V1.COL_WIDTH, V1.PAGE_WIDTH
NAVY, SLATE, AMBER, GREEN, GREY, BRICK, CREAM, INK = (
    V1.NAVY, V1.SLATE, V1.AMBER, V1.GREEN, V1.GREY, V1.BRICK, V1.CREAM, V1.INK)
C_R, C_H = V1.C_R, V1.C_H
LOAD_CMAP = V1.LOAD_CMAP
FS = {"axis": 8, "tick": 7.5, "title": 9, "note": 7, "small": 6.5}

# method families: one colour semantics for every figure
FAM = {"stacked": NAVY, "heuristic": AMBER, "random": GREY, "search": GREEN}
FAM_LABEL = {"stacked": "Stacked fills (default, snake)",
             "heuristic": "Placement heuristics",
             "random": "Random fills", "search": "Search endpoints"}
NAME = {"default_A4": "Default (stacked fill)", "sequential": "Default (stacked fill)",
        "snake": "Snake", "clustered": "Clustered", "least_manhattan": "Least Manhattan",
        "nmap_greedy": "NMAP greedy", "heaviest_first": "Heaviest first",
        "random": "Random, seed 0", "random_s1": "Random, seed 1",
        "random_s2": "Random, seed 2", "random_s3": "Random, seed 3",
        "random_s4": "Random, seed 4", "sa_random_s1": "Search (representative)"}
COMPACT = ("clustered", "least_manhattan", "nmap_greedy")


def family(n):
    if n.startswith("sa_"):
        return "search"
    if n.startswith("random"):
        return "random"
    if n in ("default_A4", "sequential", "snake"):
        return "stacked"
    return "heuristic"


def marker(n):
    return {"stacked": "s", "heuristic": "^", "random": "o", "search": "*"}[family(n)]


def label(n):
    return NAME.get(n, n.replace("sa_", "Search, ").replace("_s", " seed "))


OUT, PRODUCTS = V1.OUT, V1.PRODUCTS
save, dump_json, dump_csv, load, tidy = V1.save, V1.dump_json, V1.dump_csv, V1.load, V1.tidy
CAPTIONS = {}


# =====================================================================
# the controlled 4x4 instance for Fig. 5 (and the Fig. 2 fragment)
# =====================================================================
GRID = (4, 4)
KAPPA, BW = 2.0, 0.4
WPS = BW * 1e9


def _small_mesh():
    from scripts import interconnect as ic
    slots = [(float(x), float(y)) for y in range(GRID[1]) for x in range(GRID[0])]
    return ic.Mesh(slots, {"routing": "xy", "hub": "center"})


def _handoff():
    """The ffn1 -> ffn2 hand-off exactly as the 2.7B mapping produces it."""
    from scripts import llm_workload as lw
    W = se.Workload2p7B()
    base = lw.block_chain(W.cfg, W.S, "prefill", on_chip=True,
                          max_dies=W.fab.level("die").per_parent)
    names = [e["name"] for e in base]
    i = names.index("ffn2")
    return W.fab, base[i - 1], base[i]


def _flows(fab, prev_e, e, prod, cons):
    return se._one_boundary_flows(prev_e, e, list(prod), list(cons), fab)


def _score(mesh, fl):
    """Single-boundary version of the system latency term: busiest resource
    over links and ports (ports in link-time units, / kappa) plus the
    propagation of the longest path. Returns seconds and the pieces."""
    loads = se.resource_loads(fl, mesh, ports=True, kappa=KAPPA)
    links = {k: v for k, v in loads.items() if k[0] != "port"}
    ports = {k: v for k, v in loads.items() if k[0] == "port"}
    lmax, pmax = max(links.values()), max(ports.values())
    hops = [mesh.hops(*f["nodes"]) for f in fl]
    wh = sum(f["volume"] * f["width"] * h for f, h in zip(fl, hops))
    words = sum(f["volume"] * f["width"] for f in fl)
    busiest = max(lmax, pmax)
    t = busiest / WPS + max(hops) * 20e-9
    return {"t_s": t, "busiest_words": busiest, "max_link_words": lmax,
            "max_port_words_over_kappa": pmax,
            "binding": ("link" if lmax > pmax * (1 + 1e-9) else
                        "port" if pmax > lmax * (1 + 1e-9) else "tie"),
            "word_hops": wh, "words": words, "mean_hops": wh / words,
            "max_hops": max(hops), "loads": loads}


def _sa(mesh, fab, prev_e, e, start, seed, steps=1200, alpha=0.996, t0_frac=0.10):
    """Metropolis annealing over the 10 endpoints on the 16 slots: swap two
    endpoints or move one to an empty slot; the objective is the single-
    boundary latency term; schedule as the main search (1200 steps, 0.996)
    with t0 = 10% of the start's cost (declared)."""
    rng = random.Random(seed)
    prod, cons = list(start[0]), list(start[1])
    n = GRID[0] * GRID[1]

    def cost(p, c):
        return _score(mesh, _flows(fab, prev_e, e, p, c))["t_s"]
    cur = cost(prod, cons)
    best, best_pc = cur, (list(prod), list(cons))
    T = cur * t0_frac
    curve = []
    for step in range(1, steps + 1):
        p, c = list(prod), list(cons)
        used = set(p) | set(c)
        free = [s for s in range(n) if s not in used]
        if rng.random() < 0.5 or not free:          # swap two endpoints
            i, j = rng.sample(range(10), 2)
            arr = p + c
            arr[i], arr[j] = arr[j], arr[i]
            p, c = arr[:5], arr[5:]
        else:                                        # migrate to an empty slot
            i = rng.randrange(10)
            arr = p + c
            arr[i] = rng.choice(free)
            p, c = arr[:5], arr[5:]
        new = cost(p, c)
        if new <= cur or rng.random() < math.exp(-(new - cur) / max(T, 1e-12)):
            prod, cons, cur = p, c, new
            if cur < best - 1e-15:
                best, best_pc = cur, (list(prod), list(cons))
        T *= alpha
        if step % 100 == 0:
            curve.append((step, best))
    return best, best_pc, curve


def _small_instance():
    """Builds the three layouts and their loads; every number here is from
    the evaluator's own flow construction and load accumulation."""
    mesh = _small_mesh()
    fab, prev_e, e = _handoff()
    n = GRID[0] * GRID[1]
    layouts = {}
    # compact fill: the stacked default, stages in consecutive row-major slots
    compact = (list(range(0, 5)), list(range(5, 10)))
    layouts["compact_fill"] = {"prod": compact[0], "cons": compact[1],
                               "label": "Compact fill", "family": "stacked",
                               "rule": "stages in consecutive row-major slots"}
    # random fills, seeds 0-4, the best one is the representative
    rnd = {}
    for s in range(5):
        rng = random.Random(s)
        slots = rng.sample(range(n), 10)
        rnd[s] = (slots[:5], slots[5:])
        sc = _score(mesh, _flows(fab, prev_e, e, *rnd[s]))
        layouts[f"random_seed{s}"] = {"prod": rnd[s][0], "cons": rnd[s][1],
                                      "label": f"Random, seed {s}", "family": "random",
                                      "rule": "uniform choice of 10 of the 16 slots"}
    # the search: starts = compact fill and random seed 0; SA seeds 0-2
    runs = {}
    for seed in range(3):
        for sname, st in (("compact", compact), ("random0", rnd[0])):
            best, pc, curve = _sa(mesh, fab, prev_e, e, st, seed)
            runs[f"sa_{sname}_seed{seed}"] = {"t_s": best, "prod": pc[0], "cons": pc[1],
                                              "curve": curve, "start": sname, "seed": seed}
    per_seed = {}
    for k, r in runs.items():
        per_seed.setdefault(r["seed"], []).append((r["t_s"], k))
    best_over_starts = {s: min(v) for s, v in per_seed.items()}
    order = sorted(best_over_starts.items(), key=lambda kv: kv[1][0])
    med_seed, (med_t, med_key) = order[len(order) // 2]
    for s, (t, k) in best_over_starts.items():
        r = runs[k]
        layouts[f"search_seed{s}"] = {"prod": r["prod"], "cons": r["cons"],
                                      "label": f"Search, seed {s}", "family": "search",
                                      "rule": f"best of 2 starts ({r['start']})",
                                      "run": k}
    # score everything, record loads with coordinates
    for name, L in layouts.items():
        fl = _flows(fab, prev_e, e, L["prod"], L["cons"])
        sc = _score(mesh, fl)
        links, ports = [], []
        for k, v in sc["loads"].items():
            if k[0] == "port":
                x, y = mesh.coord(k[1])
                ports.append({"node": k[1], "x": x, "y": y, "side": k[2],
                              "words_over_kappa": v, "service_ms": v / WPS * 1e3})
            else:
                m = V1.SEG_RE.search(k[0]) if V1.SEG_RE else None
                import re
                m = re.search(r"seg\((\d+), (\d+)\)-\((\d+), (\d+)\)", k[0])
                x0, y0, x1, y1 = (int(g) for g in m.groups())
                links.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "dir": k[1],
                              "words": v, "flows": int(round(v / fl[0]["volume"])),
                              "service_ms": v / WPS * 1e3})
        L.update({k: v for k, v in sc.items() if k != "loads"})
        L["links"], L["ports"] = links, ports
        L["endpoints"] = ([{"id": f"P{i+1}", "node": p, "x": mesh.coord(p)[0],
                            "y": mesh.coord(p)[1], "role": "producer"}
                           for i, p in enumerate(L["prod"])] +
                          [{"id": f"C{i+1}", "node": c, "x": mesh.coord(c)[0],
                            "y": mesh.coord(c)[1], "role": "consumer"}
                           for i, c in enumerate(L["cons"])])
        L["busiest_service_ms"] = sc["busiest_words"] / WPS * 1e3
        L["max_link_service_ms"] = sc["max_link_words"] / WPS * 1e3
        L["max_port_service_ms"] = sc["max_port_words_over_kappa"] / WPS * 1e3
    best_random = min((k for k in layouts if k.startswith("random_seed")),
                      key=lambda k: layouts[k]["t_s"])
    fl0 = _flows(fab, prev_e, e, *compact)
    return {"grid": f"{GRID[0]}x{GRID[1]}", "kappa": KAPPA, "bw_gbps": BW,
            "handoff": {"from": prev_e["name"], "to": e["name"], "n_flows": len(fl0),
                        "words_per_flow": fl0[0]["volume"] * fl0[0]["width"],
                        "words_total": sum(f["volume"] * f["width"] for f in fl0),
                        "split_of_producer": prev_e["split"],
                        "port_floor_words_over_kappa": 5 * fl0[0]["volume"] / KAPPA},
            "search_protocol": {"steps": 1200, "alpha": 0.996, "t0": "10% of the start's cost",
                                "starts": ["compact fill", "random seed 0"],
                                "seeds": [0, 1, 2],
                                "statistic": "best over the 2 starts per seed; the "
                                             "representative is the median seed"},
            "representative": {"compact": "compact_fill", "random": best_random,
                               "search": f"search_seed{med_seed}"},
            "search_runs": {k: {kk: vv for kk, vv in r.items()} for k, r in runs.items()},
            "layouts": layouts}


def _draw_small(ax, L, vmax, vmin, show_key=False):
    """The 4x4 instance as a node graph: labelled endpoints, both link
    directions as parallel offset lines coloured and widened by the service
    time they owe, unused links faint, the busiest resource ringed."""
    nx, ny = GRID
    norm = Normalize(vmin, vmax)
    off = 0.09
    node_r = 0.24
    used = {}
    for l in L["links"]:
        used[(l["x0"], l["y0"], l["x1"], l["y1"], l["dir"])] = l
    for x in range(nx):
        for y in range(ny):
            for (x1, y1) in ((x + 1, y), (x, y + 1)):
                if x1 >= nx or y1 >= ny:
                    continue
                horiz = y1 == y
                for d in ("+", "-"):
                    s = 1 if d == "+" else -1
                    dx, dy = (0, s * off) if horiz else (-s * off, 0)
                    l = used.get((x, y, x1, y1, d))
                    x0e, x1e = x + node_r * (1 if horiz else 0), x1 - node_r * (1 if horiz else 0)
                    y0e, y1e = y + node_r * (0 if horiz else 1), y1 - node_r * (0 if horiz else 1)
                    if l is None:
                        ax.plot([x0e + dx, x1e + dx], [y0e + dy, y1e + dy], color="#e4e8eb",
                                lw=0.7, solid_capstyle="butt", zorder=1)
                        continue
                    frac = norm(l["service_ms"])
                    ax.plot([x0e + dx, x1e + dx], [y0e + dy, y1e + dy],
                            color=LOAD_CMAP(frac), lw=1.6 + 3.2 * frac,
                            solid_capstyle="butt", zorder=2 + frac)
                    # a small arrowhead for the direction
                    mx, my = (x0e + x1e) / 2 + dx, (y0e + y1e) / 2 + dy
                    ux, uy = ((1, 0) if horiz else (0, 1))
                    if d == "-":
                        ux, uy = -ux, -uy
                    ax.annotate("", xy=(mx + 0.06 * ux, my + 0.06 * uy),
                                xytext=(mx - 0.06 * ux, my - 0.06 * uy),
                                arrowprops=dict(arrowstyle="-|>", color="white", lw=0.4,
                                                mutation_scale=5), zorder=4)
    # nodes
    for x in range(nx):
        for y in range(ny):
            ax.add_patch(Circle((x, y), node_r, fc="#f6f8fa", ec="#c9d2d9", lw=0.6, zorder=5))
    for ep in L["endpoints"]:
        fc = SLATE if ep["role"] == "producer" else BRICK
        if ep["role"] == "producer":
            ax.add_patch(Rectangle((ep["x"] - node_r, ep["y"] - node_r), 2 * node_r,
                                   2 * node_r, fc=fc, ec="#1d2f3d", lw=0.6, zorder=6))
        else:
            ax.add_patch(Circle((ep["x"], ep["y"]), node_r, fc=fc, ec="#4a2412",
                                lw=0.6, zorder=6))
        ax.text(ep["x"], ep["y"], ep["id"], ha="center", va="center", fontsize=6.4,
                color="white", fontweight="bold", zorder=7)
    # the busiest resource: ring a link, or a port node
    top = L["busiest_words"]
    if L["binding"] in ("link", "tie"):
        for l in L["links"]:
            if l["words"] >= top - 1e-6:
                horiz = l["y0"] == l["y1"]
                s = 1 if l["dir"] == "+" else -1
                dx, dy = (0, s * off) if horiz else (-s * off, 0)
                mx, my = (l["x0"] + l["x1"]) / 2 + dx, (l["y0"] + l["y1"]) / 2 + dy
                ax.add_patch(Circle((mx, my), 0.16, fc="none", ec="#08131c", lw=1.1,
                                    zorder=8))
                # put the label where it is farthest from every node centre
                cands = [((0.0, 0.50), "center", "bottom"), ((0.0, -0.50), "center", "top"),
                         ((0.40, 0.0), "left", "center"), ((-0.40, 0.0), "right", "center")]
                nodes = [(x, y) for x in range(nx) for y in range(ny)]
                def clearance(c):
                    (ox_, oy_), ha_, va_ = c
                    tx, ty = mx + ox_, my + oy_
                    # the text box: ~0.78 wide, ~0.42 tall, anchored by ha/va
                    x0 = tx - {"center": 0.39, "left": 0.0, "right": 0.78}[ha_]
                    y0 = ty - {"center": 0.21, "bottom": 0.0, "top": 0.42}[va_]
                    x1, y1 = x0 + 0.78, y0 + 0.42
                    if x0 < -0.65 or x1 > nx - 0.35 or y0 < -0.7 or y1 > ny - 0.3:
                        return -1
                    def gap(a, b):
                        ddx = max(x0 - a, a - x1, 0.0)
                        ddy = max(y0 - b, b - y1, 0.0)
                        return math.hypot(ddx, ddy) - node_r
                    return min(gap(a, b) for a, b in nodes)
                (ox, oy), ha, va = max(cands, key=clearance)
                ax.text(mx + ox, my + oy, f"{l['flows']} flows\n{l['service_ms']:.1f} ms",
                        ha=ha, va=va, fontsize=6.2, color="#08131c", zorder=9,
                        linespacing=1.15, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.0))
                break
    if L["binding"] in ("port", "tie"):
        for p in L["ports"]:
            if p["words_over_kappa"] >= top - 1e-6:
                ax.add_patch(Circle((p["x"], p["y"]), node_r + 0.10, fc="none",
                                    ec="#08131c", lw=1.1, ls=(0, (2, 1.5)), zorder=8))
                ax.annotate(f"port {p['side']}\n{p['service_ms']:.1f} ms",
                            (p["x"], p["y"]), textcoords="offset points",
                            xytext=(0, -16), ha="center", va="top", fontsize=6.2,
                            color="#08131c", zorder=9, linespacing=1.15)
                break
    ax.set_xlim(-0.7, nx - 0.3); ax.set_ylim(-0.75, ny - 0.3)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def _small_readings(L):
    return (f"busiest resource {L['busiest_service_ms']:.1f} ms ({L['binding']})\n"
            f"{L['word_hops'] / 1e6:.1f} M word-hops")


# =====================================================================
# Fig. 5  the mechanism on a controlled 4x4 instance + the main-config ablation
# =====================================================================
def _fig5_networks(inst, names, fname, composite=True, width=PAGE_WIDTH):
    Ls = [inst["layouts"][n] for n in names]
    vmax = max(l["service_ms"] for L in Ls for l in L["links"])
    vmin = min(l["service_ms"] for L in Ls for l in L["links"]) * 0.9
    fig = plt.figure(figsize=(width, width * 0.42))
    gs = fig.add_gridspec(1, len(names) + 1, width_ratios=[1] * len(names) + [0.05],
                          wspace=0.05, left=0.01, right=0.93, top=0.86, bottom=0.14)
    for i, (n, L) in enumerate(zip(names, Ls)):
        ax = fig.add_subplot(gs[0, i])
        _draw_small(ax, L, vmax, vmin)
        ax.set_title(f"({'abc'[i]}) {L['label']}", fontsize=FS["title"],
                     color=FAM[L["family"]], pad=2)
        ax.text(0.5, -0.02, _small_readings(L), transform=ax.transAxes, fontsize=FS["note"],
                ha="center", va="top", linespacing=1.3, color=INK)
    cax = fig.add_subplot(gs[0, -1])
    sm = matplotlib.cm.ScalarMappable(norm=Normalize(vmin, vmax), cmap=LOAD_CMAP)
    cb = fig.colorbar(sm, cax=cax)
    cb.set_label("link service time (ms)", fontsize=FS["note"])
    cb.ax.tick_params(labelsize=FS["small"])
    cb.outline.set_linewidth(0.5)
    h = inst["handoff"]
    fig.text(0.47, 0.965, f"{len(Ls[0]['prod'])} producers → {len(Ls[0]['cons'])} consumers; "
             f"{h['n_flows']} flows, {h['words_total'] / 1e6:.1f} M words",
             ha="center", va="top", fontsize=FS["note"], color=INK)
    save(fig, fname, composite=composite,
         sources=["scripts/search_eval.py (live: _one_boundary_flows, resource_loads)",
                  "scripts/interconnect.py (Mesh 4x4, xy)"],
         note="controlled instance; not the 544-die layouts")
    return vmax, vmin


def _fig5_ablation(ax):
    """Same space, solver, budget, starts and seeds; only the objective
    changes. Every endpoint is re-scored under the system latency and shown
    as excess over the best resource-aware endpoint, from zero."""
    ab = load("objective_ablation_k2.json")["cells"]["k2"]
    names = ["ours", "word_hops", "max_hops"]
    labels = ["Resource-aware\n(links + ports)", "Word-hops\n(distance proxy)",
              "Max hops\n(propagation proxy)"]
    cols = [GREEN, AMBER, GREY]
    base = ab["per_objective"]["ours"]["T_best_s"]
    rows = []
    for i, n in enumerate(names):
        ends = ab["per_objective"][n]["endpoints"]
        ex = sorted(100 * (ab["rows"][e]["T_single_s"] / base - 1) for e in ends)
        rows.append({"objective": n, "excess_pct": ex})
        ax.plot([i] * len(ex), ex, marker="o", ms=5, mfc="white", mec=cols[i], mew=1.2,
                ls="none", zorder=4)
        ax.plot([i], [ex[0]], marker="_", ms=16, mew=2.0, color=cols[i], zorder=5)
        if n != "ours":
            ax.annotate(f"best proxy: +{ex[0]:.1f}%", (i, ex[0]), textcoords="offset points",
                        xytext=(0, -11), ha="center", va="top", fontsize=FS["note"],
                        color=cols[i])
        else:
            ax.annotate("reference", (i, ex[-1]), textcoords="offset points",
                        xytext=(0, 9), ha="center", va="bottom", fontsize=FS["note"],
                        color=cols[i])
    ax.axhline(0, color=GREEN, lw=0.9, ls=(0, (3, 2)), zorder=3)
    ax.set_xticks(range(3)); ax.set_xticklabels(labels, fontsize=FS["tick"])
    ax.set_xlim(-0.5, 2.5); ax.set_ylim(-2.5, 16)
    ax.set_ylabel("Excess latency vs best\nresource-aware result (%)", fontsize=FS["axis"])
    ax.set_title("(d) Objective ablation, main configuration", fontsize=FS["title"])
    ax.legend(handles=[Line2D([], [], marker="o", mfc="white", mec=INK, ls="none", ms=5),
                       Line2D([], [], marker="_", ms=14, mew=2, color=INK, ls="none")],
              labels=["one seed", "best of the three seeds"], fontsize=FS["small"],
              loc="upper left", frameon=False)
    tidy(ax, grid="y")
    return ab, base, rows


def fig5():
    inst = _small_instance()
    rep = inst["representative"]
    names = [rep["compact"], rep["random"], rep["search"]]
    vmax, vmin = _fig5_networks(inst, names, "fig5_small_mesh_triptych")
    for n in names:
        f, a = plt.subplots(figsize=(COL_WIDTH * 0.62, COL_WIDTH * 0.66))
        _draw_small(a, inst["layouts"][n], vmax, vmin)
        a.set_title(inst["layouts"][n]["label"], fontsize=FS["title"],
                    color=FAM[inst["layouts"][n]["family"]])
        a.text(0.5, -0.02, _small_readings(inst["layouts"][n]), transform=a.transAxes,
               fontsize=FS["note"], ha="center", va="top", linespacing=1.3)
        f.tight_layout()
        save(f, f"fig5_small_mesh_{n}", sources=["scripts/search_eval.py (live)"])
    # link-load profile candidate: loads in descending order for the three layouts
    f, a = plt.subplots(figsize=(COL_WIDTH * 1.1, COL_WIDTH * 0.85))
    for n in names:
        L = inst["layouts"][n]
        v = sorted((l["service_ms"] for l in L["links"]), reverse=True)
        a.step(range(1, len(v) + 1), v, where="mid", color=FAM[L["family"]], lw=1.5,
               label=L["label"])
    a.axhline(inst["layouts"][names[0]]["max_port_service_ms"], color=INK, lw=0.8,
              ls=(0, (2, 2)))
    a.text(0.98, inst["layouts"][names[0]]["max_port_service_ms"] + 0.3,
           "port floor (every consumer's ejection)", fontsize=FS["small"], ha="right",
           transform=a.get_yaxis_transform(), color=INK)
    a.set_xlabel("link directions, busiest first", fontsize=FS["axis"])
    a.set_ylabel("service time (ms)", fontsize=FS["axis"])
    a.set_title("Link-load profile of the three placements", fontsize=FS["title"])
    a.legend(fontsize=FS["small"], frameon=False)
    tidy(a)
    f.tight_layout()
    save(f, "fig5_small_mesh_load_profile", sources=["scripts/search_eval.py (live)"],
         note="candidate; the same instance as the triptych")
    f, a = plt.subplots(figsize=(COL_WIDTH * 1.05, COL_WIDTH * 0.9))
    ab, base, abrows = _fig5_ablation(a)
    f.tight_layout()
    save(f, "fig5d_objective_ablation", sources=["analysis/objective_ablation_k2.json"])
    # composite: three small-mesh panels over the ablation dot plot
    fig = plt.figure(figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.74))
    gs = fig.add_gridspec(2, 4, height_ratios=[1.0, 0.78], width_ratios=[1, 1, 1, 0.05],
                          wspace=0.05, hspace=0.42, left=0.01, right=0.93, top=0.92,
                          bottom=0.10)
    for i, n in enumerate(names):
        ax = fig.add_subplot(gs[0, i])
        L = inst["layouts"][n]
        _draw_small(ax, L, vmax, vmin)
        ax.set_title(f"({'abc'[i]}) {L['label']}", fontsize=FS["title"], color=FAM[L["family"]], pad=2)
        ax.text(0.5, -0.02, _small_readings(L), transform=ax.transAxes, fontsize=FS["note"],
                ha="center", va="top", linespacing=1.3, color=INK)
    cax = fig.add_subplot(gs[0, 3])
    sm = matplotlib.cm.ScalarMappable(norm=Normalize(vmin, vmax), cmap=LOAD_CMAP)
    cb = fig.colorbar(sm, cax=cax)
    cb.set_label("link service time (ms)", fontsize=FS["note"])
    cb.ax.tick_params(labelsize=FS["small"])
    h = inst["handoff"]
    fig.text(0.47, 0.975, f"5 producers → 5 consumers; {h['n_flows']} flows, "
             f"{h['words_total'] / 1e6:.1f} M words", ha="center", va="top",
             fontsize=FS["note"], color=INK)
    axd = fig.add_subplot(gs[1, :])
    _fig5_ablation(axd)
    axd.set_position([0.20, 0.09, 0.58, 0.30])
    save(fig, "fig5_mechanism_and_ablation", composite=True,
         sources=["scripts/search_eval.py (live)", "analysis/objective_ablation_k2.json"])
    # data
    slim = {k: v for k, v in inst.items() if k not in ("layouts", "search_runs")}
    slim["layouts"] = {n: {k: v for k, v in L.items() if k not in ("links", "ports")}
                       for n, L in inst["layouts"].items()}
    slim["search_runs"] = {k: {kk: vv for kk, vv in r.items() if kk != "curve"}
                           for k, r in inst["search_runs"].items()}
    slim["search_curves"] = {k: r["curve"] for k, r in inst["search_runs"].items()}
    dump_json("fig5_small_mesh_instance", slim, sources=["scripts/search_eval.py (live)"])
    for n, L in inst["layouts"].items():
        dump_csv(f"fig5_small_links_{n}", L["links"],
                 ["x0", "y0", "x1", "y1", "dir", "words", "flows", "service_ms"])
        dump_csv(f"fig5_small_ports_{n}", L["ports"],
                 ["node", "x", "y", "side", "words_over_kappa", "service_ms"])
        dump_csv(f"fig5_small_endpoints_{n}", L["endpoints"], ["id", "node", "x", "y", "role"])
    dump_json("fig5_ablation", {
        "protocol": "same feasible space, solver, budget, starts and seeds; only the "
                    "objective changes; every output re-scored under the system latency",
        "denominator": "the best endpoint of the resource-aware objective, "
                       f"{base * 1e3:.2f} ms",
        "excess_pct_by_objective": abrows,
        "recorded_loss_avoided_pct": {n: ab["per_objective"][n]["loss_avoided_by_ours_pct"]
                                      for n in ("word_hops", "max_hops")}},
        sources=["analysis/objective_ablation_k2.json"])
    reps = {k: inst["layouts"][v] for k, v in rep.items()}
    CAPTIONS["fig5"] = (
        "Fig. 5. Where link stacking comes from, and what the objective is worth. "
        "(a)-(c) One ffn hand-off of the 2.7B mapping, five producer dies to five consumer "
        f"dies, {h['n_flows']} flows of {h['words_per_flow'] / 1e6:.2f} M words, placed on a "
        "4x4 die mesh with XY routing, 0.4 GB/s per link direction and ports at twice "
        "the link rate; six slots stay empty. Every panel carries the same flows; only the "
        "placement differs. Each link direction is a line coloured and widened by the "
        "service time it owes; the busiest resource is ringed with its flow count. "
        f"The compact fill stacks {reps['compact']['busiest_service_ms']:.1f} ms on one link, "
        f"the best of five random fills {reps['random']['busiest_service_ms']:.1f} ms, and "
        f"the search {reps['search']['busiest_service_ms']:.1f} ms; the port floor is "
        f"{reps['search']['max_port_service_ms']:.2f} ms and never binds here. The search "
        "is the same annealer as the main configuration (1200 steps, two starts, three "
        "seeds, best over starts per seed, median seed shown). These are hand-off service "
        "costs on a controlled instance, not whole-model gains. (d) The main configuration's "
        "objective ablation: the same search with only the objective replaced, every "
        "endpoint re-scored under the system latency and shown as excess over the best "
        "resource-aware endpoint; the distance and hop proxies select layouts 11.4% and "
        "11.2% slower at their best seed.")
    return inst


# =====================================================================
# Fig. 2  platform workflow with a real routing fragment
# =====================================================================
def _box(ax, xy, w, h, text, fc="#eef2f6", ec=NAVY, fs=7.0, lw=0.8):
    ax.add_patch(FancyBboxPatch(xy, w, h, boxstyle="round,pad=0.010,rounding_size=0.015",
                                fc=fc, ec=ec, lw=lw, zorder=3))
    ax.text(xy[0] + w / 2, xy[1] + h / 2, text, ha="center", va="center", fontsize=fs,
            zorder=4, linespacing=1.25)


def _arrow(ax, p0, p1, ec=NAVY, lw=1.0, ls="-", rad=0.0):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=8, color=ec,
                                 lw=lw, ls=ls, zorder=2, connectionstyle=f"arc3,rad={rad}",
                                 shrinkA=1, shrinkB=1))


def fig2(inst):
    L = inst["layouts"][inst["representative"]["compact"]]
    hot = max(L["links"], key=lambda l: l["words"])
    wpf = inst["handoff"]["words_per_flow"]
    fig, ax = plt.subplots(figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.50))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    y1, h1 = 0.74, 0.16
    row = [(0.020, 0.150, "Workload and\nhardware\nconfiguration"),
           (0.200, 0.150, "Mapping and\ndependencies\n(tiling, splits)"),
           (0.380, 0.165, "Placement and\nrouting: die and\nmacro levels"),
           (0.575, 0.165, "Link and port\nloads per\nhand-off"),
           (0.770, 0.210, "Latency: max per stage,\nsum over stages\nDynamic energy: word-hops")]
    for x, w, txt in row:
        _box(ax, (x, y1), w, h1, txt, fs=6.8)
    for i in range(len(row) - 1):
        _arrow(ax, (row[i][0] + row[i][1] + 0.004, y1 + h1 / 2), (row[i + 1][0] - 0.004, y1 + h1 / 2))
    y2, h2 = 0.47, 0.13
    _box(ax, (0.575, y2), 0.165, h2, "Phase analysis\nB and device rate", fs=6.8)
    _box(ax, (0.770, y2), 0.210, h2, "DP over block cuts\nSA over die placement\nenumeration in a die",
         fc="#eaf3ed", ec=GREEN, fs=6.8)
    _arrow(ax, (0.900, y1), (0.900, y2 + h2 + 0.004), ec=GREEN)
    _arrow(ax, (0.800, y1), (0.680, y2 + h2 + 0.004), ec=SLATE, ls=(0, (3, 2)))
    ax.plot([0.800, 0.800, 0.462], [y2, 0.415, 0.415], color=GREEN, lw=1.0, zorder=2)
    _arrow(ax, (0.462, 0.415), (0.462, y1 - 0.004), ec=GREEN)
    ax.text(0.630, 0.405, "revised placement", fontsize=6.4, color=GREEN, ha="center", va="top")
    # the real routing fragment, from the Fig. 5 instance
    ex = fig.add_axes([0.02, 0.04, 0.50, 0.50])
    ex.set_xlim(-0.6, 4.4); ex.set_ylim(-0.9, 1.9); ex.axis("off")
    ex.text(-0.5, 1.75, "One link of the Fig. 5 instance (compact fill)", fontsize=7.2,
            va="top", ha="left", color=INK)
    # three nodes on a row: producer -> shared link -> consumer, plus a second producer above
    for (x, y, kind, lab) in ((0, 0.4, "P", "P"), (1, 1.2, "P", "P"), (2, 0.4, "", ""),
                              (3, 0.4, "C", "C")):
        if kind == "P":
            ex.add_patch(Rectangle((x - 0.22, y - 0.22), 0.44, 0.44, fc=SLATE, ec="#1d2f3d", lw=0.6, zorder=5))
        elif kind == "C":
            ex.add_patch(Circle((x, y), 0.22, fc=BRICK, ec="#4a2412", lw=0.6, zorder=5))
        else:
            ex.add_patch(Circle((x, y), 0.22, fc="#f6f8fa", ec="#c9d2d9", lw=0.6, zorder=5))
        if lab:
            ex.text(x, y, lab, ha="center", va="center", fontsize=6.4, color="white",
                    fontweight="bold", zorder=6)
    ex.plot([0.25, 1.75], [0.4, 0.4], color=LOAD_CMAP(0.35), lw=2.4, zorder=3)
    ex.plot([1, 1, 1.75], [0.95, 0.4, 0.4], color=LOAD_CMAP(0.35), lw=2.4, zorder=3)
    ex.plot([2.25, 2.75], [0.4, 0.4], color=LOAD_CMAP(0.95), lw=4.0, zorder=3)
    ex.add_patch(Circle((2.5, 0.4), 0.16, fc="none", ec="#08131c", lw=1.0, zorder=7))
    ex.text(2.5, 0.72, f"shared link: {hot['flows']} flows\n"
            f"{hot['flows']} x {wpf / 1e6:.2f} M = {hot['words'] / 1e6:.1f} M words\n"
            f"{hot['words'] / 1e6:.1f} M / 0.4 GB/s = {hot['service_ms']:.1f} ms",
            fontsize=6.3, ha="center", va="bottom", linespacing=1.3, color="#08131c")
    ex.text(3.0, -0.05, f"consumer port: 5 flows\n5.24 M words / κ=2 → "
            f"{L['max_port_service_ms']:.2f} ms", fontsize=6.3, ha="center", va="top",
            linespacing=1.3, color=BRICK)
    ex.text(-0.5, -0.55, "stage time = max over links and ports\n"
            "package latency = Σ stages + propagation\n"
            "communication energy = Σ words × hops × 10 pJ",
            fontsize=6.4, ha="left", va="top", linespacing=1.35, color=INK)
    save(fig, "fig2_platform_workflow", composite=True,
         sources=["scripts/search_eval.py (live: the Fig. 5 instance's compact fill)"],
         note="the fragment's numbers are the compact fill's busiest link and one consumer port")
    CAPTIONS["fig2"] = (
        "Fig. 2. The platform. The workload and hardware configuration enter the mapping, "
        "which fixes the logical dependencies; placement and routing at the die and macro "
        "levels turn them into per-hand-off link and port loads; latency takes the maximum "
        "over resources within a stage and the sum over stages, dynamic energy the routed "
        "word-hops. The phase analysis and the deployment search (a dynamic program over "
        "block cuts, simulated annealing over die placement, enumeration inside a die) read "
        "the same costs; the search feeds placements back. Lower left: one link of the "
        f"Fig. 5 instance under the compact fill, where {hot['flows']} flows of "
        f"{wpf / 1e6:.2f} M words share a link and owe {hot['service_ms']:.1f} ms at "
        "0.4 GB/s, while a consumer's ejection port owes "
        f"{L['max_port_service_ms']:.2f} ms with ports at twice the link rate.")


# =====================================================================
# Fig. 3  external references
# =====================================================================
def _spearman(x, y):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                rk[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return rk
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den


def _fig3a(ax):
    t1 = load("simba_t1.json")
    rows = t1["rows"]
    dist = [max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a in r["seating"] for b in r["seating"])
            for r in rows]
    x = np.arange(len(rows))
    meas = [r["measured_norm"] for r in rows]
    lo = [r["ratio_max_end"] for r in rows]
    est = [r["ratio_pess"] for r in rows]
    ax.plot(x, meas, marker="s", ms=6, color=NAVY, ls="none", label="measured silicon", zorder=5)
    ax.plot(x, lo, marker="o", ms=4.5, lw=1.4, color=GREEN, label="busiest-resource bound", zorder=4)
    ax.plot(x, est, marker="D", ms=4.5, lw=1.3, ls="--", color=BRICK, mfc="white",
            label="round-serialized estimate", zorder=4)
    ax.annotate(f"{meas[-1]:.2f}× measured\n{est[-1]:.2f}× estimate",
                (x[-1], meas[-1]), textcoords="offset points", xytext=(-8, -2),
                ha="right", va="top", fontsize=FS["note"], color=INK, linespacing=1.25)
    ax.set_xticks(x); ax.set_xticklabels([f"{d:g}" for d in dist], fontsize=FS["tick"])
    ax.set_xlabel("Longest producer-consumer distance (hops)", fontsize=FS["axis"])
    ax.set_ylabel("Latency, normalized to the\nadjacent seating", fontsize=FS["axis"])
    ax.set_ylim(0.85, 2.75)
    ax.set_title("(a) SIMBA: placement-dependent latency", fontsize=FS["title"])
    ax.legend(fontsize=FS["small"], loc="upper left", frameon=False)
    tidy(ax, grid="y")
    return t1, dist


def _fig3b(ax):
    fan = load("b_fanout_24x24_rerank.json")
    r = fan["rows"]
    ref = fan["summary"]["strongest_random_under_ours"]
    names = list(r)
    rho = _spearman([r[n]["ours_words"] for n in names], [r[n]["booksim_cycles"] for n in names])
    for n in names:
        fam = family(n if not n.startswith("sa_from") else "sa_x") if n != "dispersed" else "heuristic"
        fam = "search" if n.startswith("sa_") else fam
        mk = {"stacked": "s", "heuristic": "^", "random": "o", "search": "*"}[fam]
        ax.plot([r[n]["ours_words"] / r[ref]["ours_words"]],
                [r[n]["booksim_cycles"] / r[ref]["booksim_cycles"]],
                marker=mk, ms=9 if mk == "*" else 5.5, color=FAM[fam], mec="white",
                mew=0.5, ls="none", zorder=5)
    ax.plot([1.0], [1.0], marker="o", ms=9, mfc="none", mec=INK, mew=0.9, ls="none", zorder=6)
    ax.annotate("reference\nrandom fill", (1.0, 1.0), textcoords="offset points",
                xytext=(-10, 6), fontsize=FS["small"], color=INK, ha="right", va="bottom",
                linespacing=1.2)
    ax.annotate("search endpoints", (0.72, 0.66), textcoords="offset points",
                xytext=(4, -6), fontsize=FS["small"], color=GREEN, ha="left", va="top")
    lim = [0.55, 4.2]
    ax.plot(lim, lim, color="0.6", lw=0.8, ls=(0, (4, 3)), zorder=2)
    ax.text(2.35, 2.05, "y = x", fontsize=FS["small"], color="0.45", ha="left", va="top")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(*lim); ax.set_ylim(*lim)
    for a in (ax.xaxis, ax.yaxis):
        a.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
        a.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xticks([0.6, 1, 2, 4]); ax.set_yticks([0.6, 1, 2, 4])
    ax.set_xlabel("Analytical communication cost (normalized)", fontsize=FS["axis"])
    ax.set_ylabel("BookSim batch time (normalized)", fontsize=FS["axis"])
    ax.set_title("(b) BookSim: layout ranking", fontsize=FS["title"])
    ax.text(0.04, 0.96, f"Spearman ρ = {rho:.3f}, n = {len(names)}",
            transform=ax.transAxes, fontsize=FS["note"], va="top", ha="left")
    ax.legend(handles=[Line2D([], [], marker=m, color=FAM[f], ls="none",
                              ms=8 if m == "*" else 5.5, mec="white", mew=0.5)
                       for f, m in (("stacked", "s"), ("heuristic", "^"),
                                    ("random", "o"), ("search", "*"))],
              labels=["stacked fills", "heuristics", "random fills", "search endpoints"],
              fontsize=FS["small"], loc="lower right", frameon=False)
    tidy(ax)
    return fan, ref, rho, names


def fig3():
    SRC = ["analysis/simba_t1.json", "analysis/b_fanout_24x24_rerank.json"]
    fig, axes = plt.subplots(1, 2, figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.40))
    t1, dist = _fig3a(axes[0])
    fan, ref, rho, names = _fig3b(axes[1])
    fig.tight_layout()
    save(fig, "fig3_external_validation", composite=True, sources=SRC)
    for tag, fn in (("fig3a_simba_placement", _fig3a), ("fig3b_booksim_ranking", _fig3b)):
        f, a = plt.subplots(figsize=(COL_WIDTH * 1.2, COL_WIDTH * 1.0))
        fn(a); f.tight_layout(); save(f, tag, sources=SRC)
    r = fan["rows"]
    dump_csv("fig3_simba_t1", [
        {"longest_pair_hops": d, "measured_norm": x["measured_norm"],
         "bound_norm": x["ratio_max_end"], "round_serialized_norm": x["ratio_pess"]}
        for d, x in zip(dist, t1["rows"])],
        ["longest_pair_hops", "measured_norm", "bound_norm", "round_serialized_norm"], sources=SRC[:1])
    dump_csv("fig3_booksim_candidates", [
        {"candidate": n, "analytic_words": r[n]["ours_words"], "booksim_cycles": r[n]["booksim_cycles"],
         "analytic_rel": r[n]["ours_words"] / r[ref]["ours_words"],
         "booksim_rel": r[n]["booksim_cycles"] / r[ref]["booksim_cycles"],
         "packets_in_this_candidate_batch": r[n]["packets"], "binding": r[n]["busiest_is"]}
        for n in names],
        ["candidate", "analytic_words", "booksim_cycles", "analytic_rel", "booksim_rel",
         "packets_in_this_candidate_batch", "binding"], sources=SRC[1:])
    dump_json("fig3_booksim_rho", {
        "n_candidates": len(names), "candidates": names,
        "spearman_rho_average_ranks": rho,
        "recorded_rho_in_source": fan["summary"]["spearman"],
        "note": "the recorded 0.962 assigned ordinal ranks to the two tied analytic values; "
                "with average ranks (the standard Spearman with ties) the same 13 "
                "candidates give this value, and it is what the figure prints",
        "reference": ref, "packets_per_candidate_batch": r[ref]["packets"],
        "search_endpoint_gain_booksim_pct": {k: v["gain_booksim_vs_booksim_best_random_pct"]
                                            for k, v in fan["summary"]["endpoints"].items()}},
        sources=SRC[1:])
    ends = fan["summary"]["endpoints"]
    g = [v["gain_booksim_vs_booksim_best_random_pct"] for v in ends.values()]
    CAPTIONS["fig3"] = (
        "Fig. 3. What the cost model is checked against. (a) The published placement "
        "measurements of the Simba package (Shao et al., Fig. 9: one convolution layer, "
        "res4a_branch1, on four chiplets with a fixed tiling) against the platform's two "
        "estimates for the same five seatings, decoded from the paper into their longest "
        "producer-to-consumer distance. Every series is normalized to its own adjacent "
        "seating. The busiest-resource bound is nearly flat because the busiest link carries "
        "the same load in every seating; the round-serialized estimate, which adds the "
        f"packet round trips, follows the measured ladder from below (measured {t1['rows'][-1]['measured_norm']:.2f}x, "
        f"estimate {t1['rows'][-1]['ratio_pess']:.2f}x at the farthest seating). The two are model "
        "variants, not a confidence band. (b) An independent instance: a synthetic fan-out "
        "batch on a 24x24 die mesh with 17 dies per stage and ports at the link rate, whose "
        f"{len(names)} candidate placements are scored by the analytical bottleneck cost and by "
        "the BookSim packet simulator, each normalized to the same random fill. The dashed "
        "line is y = x; the rank correlation, not the line, is the claim. The four search "
        f"endpoints are {min(g):.0f} to {max(g):.0f}% below the reference under BookSim; these "
        "are network-batch times, not whole-model gains.")


# =====================================================================
# Fig. 4  system gain and dynamic energy
# =====================================================================
BAR_ORDER = ["default_A4", "snake", "clustered", "heaviest_first", "nmap_greedy",
             "least_manhattan", "random_s3", "sa_random_s1"]


def _fig4a(ax, with_points=True):
    mc = load("main_config_results.json")["rows"]
    mt = {n: r["prefill"]["0.4"] for n, r in mc.items()}
    ys = np.arange(len(BAR_ORDER))[::-1]
    T = {n: mt[n]["T_s"] * 1e3 for n in mc}
    for y, n in zip(ys, BAR_ORDER):
        r = mt[n]
        R = (r["layers_s"] + r["propagation_s"]) * 1e3
        H = r["H_s"] * 1e3
        ax.barh(y, R, color=C_R, ec="white", lw=0.5, height=0.62, zorder=3)
        ax.barh(y, H, left=R, color=C_H, ec="white", lw=0.5, height=0.62, zorder=3)
        ax.text(R + H + 45, y, f"{R + H:.0f}", va="center", ha="left", fontsize=FS["note"],
                color=FAM[family(n)], zorder=4)
    if with_points:                     # the five random fills and the nine endpoints
        yr, ysr = ys[BAR_ORDER.index("random_s3")], ys[-1]
        rnd = [T[n] for n in mc if n.startswith("random")]
        sea = [T[n] for n in mc if n.startswith("sa_")]
        ax.plot(rnd, [yr + 0.46] * len(rnd), marker="|", ms=7, mew=1.0, color=GREY, ls="none", zorder=5)
        ax.plot(sea, [ysr - 0.46] * len(sea), marker="|", ms=7, mew=1.0, color=GREEN, ls="none", zorder=5)
        ax.text(max(rnd) + 45, yr + 0.46, "5 random fills", fontsize=FS["small"], color=GREY, va="center")
        ax.text(max(sea) + 45, ysr - 0.46, "9 search endpoints", fontsize=FS["small"], color=GREEN, va="center")
    ax.set_yticks(ys)
    ax.set_yticklabels([label(n) if n != "sa_random_s1" else "Search" for n in BAR_ORDER],
                       fontsize=FS["tick"])
    for tick, n in zip(ax.get_yticklabels(), BAR_ORDER):
        tick.set_color(FAM[family(n)])
    ax.set_xlabel("Whole-model prefill latency (ms)", fontsize=FS["axis"])
    ax.set_xlim(0, 5000)
    ysr, yr = ys[-1], ys[BAR_ORDER.index("random_s3")]
    ax.annotate("", xy=(T["sa_random_s1"], ysr + 0.50), xytext=(T["random_s3"], ysr + 0.50),
                arrowprops=dict(arrowstyle="<|-|>", color=GREEN, lw=0.9, mutation_scale=7))
    ax.text(T["random_s3"] + 60, ysr + 0.50,
            f"{100 * (1 - T['sa_random_s1'] / T['random_s3']):.2f}% below the best random fill",
            fontsize=FS["note"], color=GREEN, ha="left", va="center")
    yb = ysr - 0.95
    ax.annotate("", xy=(T["sa_random_s1"], yb), xytext=(T["default_A4"], yb),
                arrowprops=dict(arrowstyle="<|-|>", color=NAVY, lw=0.9, mutation_scale=7))
    ax.text((T["sa_random_s1"] + T["default_A4"]) / 2, yb - 0.20,
            f"{100 * (1 - T['sa_random_s1'] / T['default_A4']):.1f}% below the default fill",
            fontsize=FS["note"], color=NAVY, ha="center", va="top")
    ax.set_ylim(yb - 0.95, max(ys) + 0.6)
    ax.legend(handles=[Rectangle((0, 0), 1, 1, fc=C_R, ec="none"),
                       Rectangle((0, 0), 1, 1, fc=C_H, ec="none")],
              labels=["Non-communication", "Package communication"], fontsize=FS["note"],
              loc="center right", bbox_to_anchor=(1.0, 0.50), frameon=False)
    ax.set_title("(a) Whole-model latency of the evaluated placements", fontsize=FS["title"])
    tidy(ax, grid="x")
    return mt, T


def _fig4b(ax):
    en = load("energy_export.json")["rows"]
    ref = "random_s3"
    Tr, Er = en[ref]["T_s"], en[ref]["E_total_J"]
    seen = set()
    for n, e in en.items():
        if n == "sequential":
            continue
        fam = family(n)
        big = n in ("random_s3", "sa_random_s1")
        ax.plot([e["T_s"] * 1e3], [e["E_total_J"]], marker=marker(n),
                ms=(11 if fam == "search" else 7) if big else (7 if fam == "search" else 4.5),
                color=FAM[fam], mec=INK if big else "white", mew=0.8 if big else 0.4,
                ls="none", zorder=6 if big else 5, label=None if fam in seen else FAM_LABEL[fam])
        seen.add(fam)
    dT = lambda n: 100 * (en[n]["T_s"] / Tr - 1)
    dE = lambda n: 100 * (en[n]["E_total_J"] / Er - 1)
    notes = (("default_A4", "Default (stacked fill)", (-10, 2), "right", "center"),
             ("snake", "Snake", (-8, 4), "right", "bottom"),
             ("heaviest_first", "Heaviest first", (8, 0), "left", "center"),
             ("least_manhattan", f"Least Manhattan\n{dE('least_manhattan'):+.1f}% energy, "
                                 f"{dT('least_manhattan'):+.1f}% latency", (0, 12), "center", "bottom"),
             ("clustered", f"Clustered, {dT('clustered'):+.1f}% latency", (10, 0), "left", "center"),
             ("random_s3", "best random fill", (12, -4), "left", "top"),
             ("sa_random_s1", "search\n(representative)", (0, -12), "center", "top"))
    for n, lab, off, ha, va in notes:
        ax.annotate(lab, (en[n]["T_s"] * 1e3, en[n]["E_total_J"]), textcoords="offset points",
                    xytext=off, fontsize=FS["small"], ha=ha, va=va, color=FAM[family(n)],
                    linespacing=1.2)
    ax.plot([Tr * 1e3, en["sa_random_s1"]["T_s"] * 1e3], [Er, en["sa_random_s1"]["E_total_J"]],
            color=GREEN, lw=0.9, ls=(0, (3, 2)), zorder=4)
    ax.text(1830, 2.560, f"search vs best random fill:\n{dT('sa_random_s1'):+.2f}% latency, "
            f"{dE('sa_random_s1'):+.2f}% dynamic energy", fontsize=FS["note"], color=GREEN,
            ha="left", va="top", linespacing=1.3)
    ax.set_xlim(1750, 4550); ax.set_ylim(2.315, 2.57)
    ax.set_xlabel("Whole-model prefill latency (ms)", fontsize=FS["axis"])
    ax.set_ylabel("System dynamic energy (J)", fontsize=FS["axis"])
    ax.set_title("(b) Latency and dynamic energy", fontsize=FS["title"])
    ax.legend(fontsize=FS["small"], loc="upper right", frameon=False)
    tidy(ax)
    return en, ref


def _fig4c(ax):
    it = load("intra_die_integration.json")
    a = it["per_anchor"]["0.4"]
    ship = a["T_layer_shipped_incl_pkg_s"] * 1e3
    best = a["T_layer_best_incl_pkg_s"] * 1e3
    rest = (a["fixed_rest_s"] + a["package_handoffs_per_layer_s_at_0.4"]) * 1e3
    b1 = [a["dies"]["attn"]["shipped_s"] * 1e3, a["dies"]["attn"]["best_s"] * 1e3]
    b2 = [a["dies"]["ffn"]["shipped_s"] * 1e3, a["dies"]["ffn"]["best_s"] * 1e3]
    xs = [0, 1]
    ax.bar(xs, b1, width=0.5, color="#9db8c9", ec="white", lw=0.6, label="Attention die", zorder=3)
    ax.bar(xs, b2, bottom=b1, width=0.5, color="#c9a86a", ec="white", lw=0.6, label="FFN die", zorder=3)
    ax.bar(xs, [rest, rest], bottom=np.add(b1, b2), width=0.5, color="#dfe4e8", ec="white", lw=0.6,
           label="Other costs incl.\npackage transfers", zorder=3)
    for x, tot in zip(xs, (ship, best)):
        ax.text(x, tot + 0.6, f"{tot:.2f} ms", ha="center", va="bottom", fontsize=FS["note"], color=INK)
    ax.plot([1.32, 1.32], [best, ship], color=GREEN, lw=1.0, zorder=4)
    ax.plot([1.27, 1.32], [best, best], color=GREEN, lw=1.0); ax.plot([1.27, 1.32], [ship, ship], color=GREEN, lw=1.0)
    ax.text(1.36, (best + ship) / 2, f"{100 * (1 - best / ship):.2f}% lower\nlayer latency",
            fontsize=FS["note"], color=GREEN, ha="left", va="center", linespacing=1.25)
    ax.set_xticks(xs); ax.set_xticklabels(["Contiguous\nassignment", "Exhaustive\noptimum"], fontsize=FS["tick"])
    ax.set_xlim(-0.5, 1.9)
    ax.set_ylabel("Layer latency (ms)", fontsize=FS["axis"])
    ax.set_ylim(0, ship * 1.75)
    ax.set_title("(c) Whole-layer impact of\nintra-die assignment", fontsize=FS["title"])
    ax.legend(fontsize=FS["small"], loc="upper left", frameon=False, labelspacing=0.3)
    tidy(ax, grid="y")
    return it, ship, best, rest


def fig4():
    SRC = ["analysis/main_config_results.json", "analysis/energy_export.json",
           "analysis/intra_die_integration.json"]
    fig = plt.figure(figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.74))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 0.95], width_ratios=[2, 2, 1.25],
                          hspace=0.45, wspace=0.42)
    mt, T = _fig4a(fig.add_subplot(gs[0, :]))
    en, ref = _fig4b(fig.add_subplot(gs[1, :2]))
    it, ship, best, rest = _fig4c(fig.add_subplot(gs[1, 2]))
    save(fig, "fig4_deployment_gain", composite=True, sources=SRC)
    for tag, fn, size in (("fig4a_latency_breakdown", _fig4a, (PAGE_WIDTH * 0.66, 2.6)),
                          ("fig4b_latency_energy", _fig4b, (COL_WIDTH * 1.35, COL_WIDTH * 1.05)),
                          ("fig4c_intra_die_layer", _fig4c, (COL_WIDTH * 0.95, COL_WIDTH * 1.05))):
        f, a = plt.subplots(figsize=size); fn(a); f.tight_layout(); save(f, tag, sources=SRC)
    dump_csv("fig4_layouts", [
        {"layout_id": n, "name": label(n), "family": family(n),
         "T_prefill_ms": mt[n]["T_s"] * 1e3, "R_ms": (mt[n]["layers_s"] + mt[n]["propagation_s"]) * 1e3,
         "H_ms": mt[n]["H_s"] * 1e3, "E_dynamic_J": en[n]["E_total_J"],
         "dT_vs_random_s3_pct": 100 * (en[n]["T_s"] / en[ref]["T_s"] - 1),
         "dE_vs_random_s3_pct": 100 * (en[n]["E_total_J"] / en[ref]["E_total_J"] - 1)}
        for n in en if n != "sequential"],
        ["layout_id", "name", "family", "T_prefill_ms", "R_ms", "H_ms", "E_dynamic_J",
         "dT_vs_random_s3_pct", "dE_vs_random_s3_pct"], sources=SRC)
    st = load("main_config_results.json")["stats"]["prefill"]
    CAPTIONS["fig4"] = (
        "Fig. 4. What the deployment choice is worth, and what it costs. Main configuration: "
        "2.7B class, 512-token serial prefill, 544 of 576 dies on a 24x24 mesh, XY routing, "
        "0.4 GB/s per link direction, ports at twice the link rate. (a) Whole-model latency "
        "of the evaluated placements, split into the non-communication cost (compute, weight "
        "write, digital unit) and the package hand-offs; the ticks under the random and search "
        "bars are the five random fills (seeds 0 to 4) and the nine search endpoints. The "
        "search bar is the representative layout, the median of three seeds after taking the "
        f"best of three starts per seed: {100*(1-T['sa_random_s1']/T['random_s3']):.2f}% below "
        f"the best random fill ({T['random_s3']:.2f} ms; range over seeds "
        f"{st['0.4']['G_range_pct'] if '0.4' in st and 'G_range_pct' in st['0.4'] else '9.66 to 10.12'}%) "
        f"and {100*(1-T['sa_random_s1']/T['default_A4']):.1f}% below the default stacked fill "
        f"({T['default_A4']:.2f} ms). (b) The same layouts in latency and system dynamic energy "
        "(no static term). The three short-path heuristics save about 7.3% of dynamic energy "
        "against the best random fill at different latency costs: Least Manhattan +1.8%, "
        "NMAP greedy +4.0%, Clustered +20.4%; the search lowers latency by 9.91% and dynamic "
        "energy by 0.26%. (c) A different instance: the GPT-2-medium class layer with an "
        "attention die and an FFN die, each a 2x4 macro mesh, at 0.4 GB/s; the exhaustive "
        "optimum over 280 and 70 macro assignments against the contiguous assignment, with "
        f"the fixed rest of the layer ({rest:.2f} ms incl. two package transfers) included. "
        "Energy is not modelled at this level.")


# =====================================================================
# Fig. 6  conditions
# =====================================================================
def _fig6a(ax):
    sl = load("bw_slice_k2.json")
    pts = sorted(sl["points"].values(), key=lambda p: p["B_gbps"])
    B = [p["B_gbps"] for p in pts]
    G, eta, r = ([100 * p[k] for p in pts] for k in ("G", "eta", "r"))
    ax.axvspan(sl["B_minus_gbps"], sl["B_plus_gbps"], color=CREAM, alpha=0.55, lw=0, zorder=1)
    ax.text(np.sqrt(sl["B_minus_gbps"] * sl["B_plus_gbps"]), 74, "placement-\ndependent band",
            fontsize=FS["small"], ha="center", va="top", color="#6b5a2a", linespacing=1.2)
    ax.plot(B, r, ls="--", lw=1.2, color=AMBER, marker="s", ms=3.5, zorder=3,
            label="r: communication share of the reference")
    ax.plot(B, eta, ls=(0, (1.5, 1.8)), lw=1.3, color=SLATE, marker="D", ms=3.5, zorder=4,
            label="\u03b7: communication improvement of the pair")
    ax.plot(B, G, marker="o", ms=4.5, lw=1.7, color=GREEN, zorder=5, label="G: whole-model gain")
    for p in pts:
        if abs(p["B_gbps"] - 0.4) < 1e-6:
            ax.annotate(f"{100 * p['G']:.2f}%", (p["B_gbps"], 100 * p["G"]),
                        textcoords="offset points", xytext=(0, -8), ha="center", va="top",
                        fontsize=FS["note"], color=GREEN)
        elif 0.85 < p["B_gbps"] < 0.9:
            ax.annotate(f"{100 * p['G']:.2f}%", (p["B_gbps"], 100 * p["G"]),
                        textcoords="offset points", xytext=(0, 7), ha="center", va="bottom",
                        fontsize=FS["note"], color=GREEN)
        elif p["B_gbps"] > 10:
            ax.annotate(f"{100 * p['G']:.2f}%", (p["B_gbps"], 100 * p["G"]),
                        textcoords="offset points", xytext=(-6, 8), ha="right", va="bottom",
                        fontsize=FS["note"], color=GREEN)
    ax.set_xscale("log")
    ax.set_xticks([0.2, 0.4, 0.872, 2, 12.5])
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xlabel("Link bandwidth per direction (GB/s)", fontsize=FS["axis"])
    ax.set_ylabel("Percent", fontsize=FS["axis"])
    ax.set_ylim(0, 80)
    ax.text(0.97, 0.94, "G = η · r at every point", transform=ax.transAxes,
            fontsize=FS["note"], ha="right", va="top", color=INK)
    ax.set_title("(a) Bandwidth response of fixed placements", fontsize=FS["title"])
    ax.legend(fontsize=FS["small"], loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=1,
              frameon=False, handlelength=2.2)
    tidy(ax)
    return sl, pts


def _fig6b(ax, bw="0.4"):
    sw = load("kappa_geometry_sweep.json")
    stat = {}
    for cell_name, cell in sw["cells"].items():
        grid, k = cell_name.split("/")
        per_seed = {}
        for rn in cell["runs"]:
            per_seed.setdefault(rn.rsplit("_s", 1)[1], []).append(cell["rows"][rn]["T_s"][bw])
        bos = [min(v) for v in per_seed.values()]
        base = min(v["T_s"][bw] for n, v in cell["rows"].items() if not n.startswith("sa_"))
        gains = sorted(100 * (1 - t / base) for t in bos)
        binding = sorted({cell["rows"][rn]["binding"] for rn in cell["runs"]})
        stat[(grid, float(k[1:]))] = {"median": gains[len(gains) // 2], "lo": gains[0],
                                      "hi": gains[-1], "baseline_ms": base * 1e3,
                                      "endpoint_binding": binding}
    for grid, col, mk in (("24x24", GREEN, "o"), ("12x48", SLATE, "s")):
        ks = sorted(k for (g, k) in stat if g == grid)
        med = [stat[(grid, k)]["median"] for k in ks]
        lo = [stat[(grid, k)]["median"] - stat[(grid, k)]["lo"] for k in ks]
        hi = [stat[(grid, k)]["hi"] - stat[(grid, k)]["median"] for k in ks]
        ax.errorbar(ks, med, yerr=[lo, hi], marker=mk, ms=5, lw=1.5, color=col, capsize=2.5,
                    elinewidth=0.9, label=f"{grid} package", zorder=4)
    ax.set_xticks([1, 2, 4]); ax.set_xlim(0.7, 4.4); ax.set_ylim(0, 12)
    ax.set_xlabel("Port capacity / link capacity, κ", fontsize=FS["axis"])
    ax.set_ylabel("Gain over the strongest baseline\nof the same cell (%)", fontsize=FS["axis"])
    ax.set_title("(b) Port capacity and mesh geometry", fontsize=FS["title"])
    ax.text(1.12, 3.9, "port capacity limits\nthe remaining gain", fontsize=FS["small"], ha="left",
            va="bottom", color=INK, linespacing=1.25)
    ax.text(3.0, 11.3, "ports no longer bind", fontsize=FS["small"], ha="center", va="top", color=INK)
    leg = ax.legend(fontsize=FS["small"], loc="lower right", frameon=False,
                    title="median of three seeds; bars: range")
    leg.get_title().set_fontsize(FS["small"])
    tidy(ax)
    return stat


def fig6():
    SRC = ["analysis/bw_slice_k2.json", "analysis/kappa_geometry_sweep.json"]
    fig, axes = plt.subplots(1, 2, figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.40))
    sl, pts = _fig6a(axes[0]); stat = _fig6b(axes[1])
    fig.tight_layout()
    save(fig, "fig6_conditions", composite=True, sources=SRC)
    for tag, fn in (("fig6a_bandwidth_response", _fig6a), ("fig6b_port_geometry", _fig6b)):
        f, a = plt.subplots(figsize=(COL_WIDTH * 1.25, COL_WIDTH * 1.0)); fn(a); f.tight_layout()
        save(f, tag, sources=SRC)
    dump_csv("fig6_bandwidth_response", [
        {"point": k, "B_gbps": p["B_gbps"], "region": p["region"], "T_reference_ms": p["T_s_ref"] * 1e3,
         "T_selected_ms": p["T_s_sel"] * 1e3, "G_ratio": p["G"], "eta_ratio": p["eta"], "r_ratio": p["r"],
         "G_pct": 100 * p["G"], "eta_pct": 100 * p["eta"], "r_pct": 100 * p["r"]}
        for k, p in sl["points"].items()],
        ["point", "B_gbps", "region", "T_reference_ms", "T_selected_ms", "G_ratio", "eta_ratio",
         "r_ratio", "G_pct", "eta_pct", "r_pct"], sources=SRC[:1])
    dump_csv("fig6_port_geometry", [
        {"grid": g, "kappa": k, "gain_median_pct": v["median"], "gain_min_pct": v["lo"],
         "gain_max_pct": v["hi"], "strongest_baseline_ms": v["baseline_ms"],
         "endpoint_binding": "/".join(v["endpoint_binding"]),
         "statistic": "per seed the best of 3 starts, then median and min-max over 3 seeds; "
                      "denominator = the cell's strongest evaluated baseline"}
        for (g, k), v in sorted(stat.items())],
        ["grid", "kappa", "gain_median_pct", "gain_min_pct", "gain_max_pct", "strongest_baseline_ms",
         "endpoint_binding", "statistic"], sources=SRC[1:])
    CAPTIONS["fig6"] = (
        "Fig. 6. The conditions that set the value of placement. (a) One fixed pair of "
        "layouts, the best random fill and the representative search layout of Fig. 4, "
        "re-scored at each bandwidth without a new search. The communication share r of the "
        "reference, the communication improvement η of the pair and the whole-model gain "
        "G are all percentages, and G = η r holds at every point; the shaded band is the "
        "placement-dependent band of Fig. 1(b) for the seven named rules at the NeuRRAM row "
        f"rate ({sl['B_minus_gbps']:.3f} to {sl['B_plus_gbps']:.3f} GB/s). (b) The search gain "
        "against the strongest evaluated baseline of each cell for two package geometries and "
        "three port capacities at 0.4 GB/s: per seed the best of three starts, then the "
        "median and the range over three seeds. At κ = 1 the port capacity limits the "
        "remaining gain; at κ = 2 and 4 the endpoints are link-bound and the two "
        "geometries agree within the seed range.")


# =====================================================================
# Fig. 1
# =====================================================================
def fig1():
    """Fig. 1 is the print version of the standing phase diagram, rendered by
    its own generator with the outputs redirected into this run; the two
    panels are cropped from the same rendering."""
    from scripts import fig_phase_isobar_print as P
    src = ["scripts/fig_phase_isobar_print.py", "scripts/fig_phase_isobar.py",
           "analysis/phase_diagram_isobar_k2.json"]
    P.OUT_PNG = os.path.join(OUT["preview"], "fig1_phase_diagram.png")
    P.OUT_PDF = os.path.join(OUT["composites"], "fig1_phase_diagram.pdf")
    P.main()
    fig = plt.gcf()
    fig.savefig(os.path.join(OUT["composites"], "fig1_phase_diagram.svg"))
    PRODUCTS.append({"name": "fig1_phase_diagram", "kind": "composites",
                     "files": ["composites/fig1_phase_diagram.pdf", "composites/fig1_phase_diagram.svg",
                               "preview/fig1_phase_diagram.png"], "sources": src,
                     "note": "identical to analysis/phase_diagram_isobar_print_k2 (final form)"})
    print("   composites/fig1_phase_diagram.pdf|svg  preview/fig1_phase_diagram.png")
    r = fig.canvas.get_renderer()
    for ax, tag in zip(fig.axes[:2], ("fig1a_intra_die_phase", "fig1b_inter_die_phase")):
        bb = ax.get_tightbbox(r).transformed(fig.dpi_scale_trans.inverted()).expanded(1.04, 1.06)
        for ext, kind in (("pdf", "panels"), ("svg", "panels"), ("png", "preview")):
            fig.savefig(os.path.join(OUT[kind], f"{tag}.{ext}"), bbox_inches=bb, dpi=300)
        PRODUCTS.append({"name": tag, "kind": "panels",
                         "files": [f"panels/{tag}.pdf", f"panels/{tag}.svg", f"preview/{tag}.png"],
                         "sources": src, "note": "cropped from the composite; the legend is on the composite"})
        print(f"   panels/{tag}.pdf|svg  preview/{tag}.png")
    plt.close(fig)
    CAPTIONS["fig1"] = (
        "Fig. 1. The placement phase diagram. Both axes are rates: the device's row-processing "
        "rate and the link bandwidth per direction. (a) Intra-die placement: one die's two "
        "co-resident operators of the GPT-2-medium class layer over all 70 macro seatings, "
        "under the per-operator overlap model, so the regions say whether communication is "
        "exposed or masked; the envelope between the placement extrema is 2.67x. (b) Inter-die "
        "placement: the 2.7B stack on 544 of 576 dies over the seven named seating rules with "
        "ports at twice the link rate, under the serial sum, so the regions say which cost "
        "dominates; the envelope is 2.66x. The dotted contour is a 20% placement latency "
        "spread. Filled diamonds are published parameters projected onto this instance "
        "(HERMES 0.4 GB/s per core-to-core link; ISAAC 4.0 GB/s per inter-tile link and "
        "6.4 GB/s per off-chip link), not measured phase positions of those chips on this "
        "workload; hollow diamonds are derived or alternative-mode values projected the same "
        "way (HERMES's 4-phase MVM; the M1076's published 2 GB/s I/O capability matched to "
        "the model's port capacity, 1.0 GB/s at kappa = 2). The dashed lines are the two "
        "bandwidth tiers evaluated in this paper, and the circles joined by a vertical line "
        "are those two configurations at the NeuRRAM row rate.")


# =====================================================================
# captions, index, manifest, main
# =====================================================================
SECTION = {"fig1": "§2.2 (first pointer in the Introduction)", "fig2": "§3.1",
           "fig3": "§3.3", "fig4": "§4.3", "fig5": "§4.3 end / §4.4",
           "fig6": "§4.5"}


def write_docs(run_id, argv):
    root = OUT["root"]
    L = ["# Formal captions (v2)\n", "Written for the paper; no development notes.\n"]
    for k in ("fig1", "fig2", "fig3", "fig4", "fig5", "fig6"):
        L.append(f"\n## {k}\n\n{CAPTIONS.get(k, '(not generated in this run)')}\n")
    open(os.path.join(root, "captions.md"), "w").write("".join(L))
    idx = [f"# Figure set v2: `{run_id}`\n\n",
           "Generated by `scripts/plot_dac2027_v2.py` into this directory only; v1 and every\n"
           "pre-existing figure are untouched. Each panel exists as PDF, SVG (text kept as\n"
           "text) and PNG preview; the numbers behind it are in `data/`; the formal captions\n"
           "are in `captions.md`. Fonts: axis 8 pt, ticks 7.5 pt, titles 9 pt, notes 6.5 to\n"
           "7 pt at the drawn size (single column 3.4 in, double column 7.16 in).\n\n"
           "| figure | paper section | claim | instance | layout ids | statistic / denominator | sources |\n"
           "|---|---|---|---|---|---|---|\n",
           f"| fig1_phase_diagram | {SECTION['fig1']} | placement is a phase with computable boundaries | (a) GPT-2-medium class ffn die, 70 seatings; (b) 2.7B on 544/576 dies, 7 rules, kappa 2 | rules by name | envelopes max/min over the set; boundaries at the NeuRRAM rate | phase_diagram_isobar_k2.json |\n",
           f"| fig2_platform_workflow | {SECTION['fig2']} | what the platform computes and where the search sits | schematic; fragment from the Fig. 5 instance's compact fill | compact_fill | one link's flows x words / bandwidth; one port / kappa | fig5_small_mesh_instance.json |\n",
           f"| fig3_external_validation | {SECTION['fig3']} | what the cost model is checked against | (a) Simba T1, 4 chiplets, 5 seatings; (b) 24x24 fan-out batch, kappa 1, 13 candidates | (b) candidate ids in fig3_booksim_candidates.csv | (a) each series / its adjacent seating; (b) both axes / the reference random fill; rho with average ranks | simba_t1.json, b_fanout_24x24_rerank.json |\n",
           f"| fig4_deployment_gain | {SECTION['fig4']} | what the deployment choice is worth and costs | main configuration; (c) GPT-2-medium class layer | random_s3 (best random), sa_random_s1 (representative), default_A4 | 9.91% = median of 3 seeds of best-over-3-starts vs random_s3 2118.71 ms; 54.5% vs default 4192.54 ms; dE = E/E_ref - 1 | main_config_results.json, energy_export.json, intra_die_integration.json |\n",
           f"| fig5_mechanism_and_ablation | {SECTION['fig5']} | where stacking comes from; what the objective is worth | (a-c) controlled 4x4 die mesh, the ffn1->ffn2 hand-off, 25 flows; (d) main configuration | compact_fill, random_seed3 (best of 0-4), search_seed (median of 0-2) | (a-c) busiest resource in link-time, word-hops; (d) excess over the best resource-aware endpoint 1886.5 ms | fig5_small_mesh_instance.json, objective_ablation_k2.json |\n",
           f"| fig6_conditions | {SECTION['fig6']} | the conditions that set the value of placement | (a) frozen pair re-scored; (b) 6 cells of the kappa x geometry sweep | random_s3 / sa_random_s1; per-cell runs | (a) G, eta, r as percentages, G = eta r; (b) per seed best of 3 starts, median and range over 3 seeds vs the cell's strongest baseline | bw_slice_k2.json, kappa_geometry_sweep.json |\n",
           "\n## Notes for the author (not for the paper)\n\n",
           "- Fig. 3(b): the source JSON records rho = 0.962 from ordinal ranks; two candidates tie on the analytic cost, and the standard Spearman with average ranks over the same 13 candidates is the value printed (see `data/fig3_booksim_rho.json`). The 154,037 packets are the size of ONE candidate's batch, not a total.\n",
           "- Fig. 5(a-c) is a new controlled instance: the 25 flows are the real ffn1->ffn2 hand-off of the 2.7B mapping, re-placed on a 4x4 mesh and re-scored by the evaluator's own flow and load code. Its numbers are hand-off service costs on that instance and are not the 24x24 stage readings of v1 (26.2 / 21.0 / 13.1 ms), which belong to the 544-die layouts.\n",
           "- Fig. 5(d) keeps the recorded denominator (the best resource-aware endpoint); the +11.4% / +11.2% labels are each proxy's best endpoint, the other seeds are drawn as points.\n",
           "- Fig. 6(b): every cell uses the same statistic, recomputed from the per-run records; the sensitivity table in main_config_results.md mixes best-of-nine values and is not the source here.\n",
           "- Only the PDFs, the data, the captions and this index are committed; SVG and PNG come back from the command in the header.\n"]
    open(os.path.join(root, "figure_index.md"), "w").write("".join(idx))
    man = {"run_id": run_id, "generator": "scripts/plot_dac2027_v2.py", "command": " ".join(argv),
           "configuration": {"model": "2.7B class", "phase": "prefill", "S": 512, "dies": "544 of 576",
                             "grid": "24x24 mesh, XY", "row_time_s": 10.14e-6, "kappa": 2.0,
                             "link_gbps": 0.4, "small_instance": {"grid": "4x4", "handoff": "ffn1->ffn2",
                                                                  "flows": 25, "kappa": 2.0, "link_gbps": 0.4}},
           "preexisting_outputs_check": V1._preexisting_check(),
           "products": PRODUCTS}
    json.dump(man, open(os.path.join(root, "manifest.json"), "w"), indent=1)
    print("   captions.md, figure_index.md, manifest.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--root", default=os.path.join(A, "figures_dac2027"))
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    root = os.path.join(args.root, args.run_id)
    OUT["root"] = root
    for k in ("panels", "composites", "data", "preview"):
        OUT[k] = os.path.join(root, k)
        os.makedirs(OUT[k], exist_ok=True)
    wanted = [w.strip() for w in args.only.split(",") if w.strip()] or ["fig5", "fig2", "fig3", "fig4", "fig6", "fig1"]
    inst = None
    for w in wanted:
        print(f"[{w}]")
        if w == "fig5":
            inst = fig5()
        elif w == "fig2":
            inst = inst or _small_instance()
            fig2(inst)
        else:
            {"fig1": fig1, "fig3": fig3, "fig4": fig4, "fig6": fig6}[w]()
    write_docs(args.run_id, sys.argv)
    print(f"\n-> {root}")


if __name__ == "__main__":
    main()
