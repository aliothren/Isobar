"""S10 task A2: why random beats the adapted rules and the resource-aware
search beats random, from the resource loads themselves. Main
configuration (24x24, kappa 2, 0.4 GB/s, prefill). For each layout: the
total routed word-hops, per-boundary maximum link load and maximum port
load (in link-time units, / kappa), the binding resource, the aggregate
A(p; kappa) = sum over the 159 serial boundaries of the per-boundary
maximum, the latency decomposition, the aggregate by boundary type, and
the top hotspots. Boundaries are aggregated one at a time (serial), never
merged into one batch.

    python3 scripts/mechanism_table.py -> analysis/mechanism_table.json + .md
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import kappa_geometry_sweep as kg
from scripts import llm_workload as lw
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_space as ss

OUT = os.path.join(se.A, "mechanism_table.json")
MD = os.path.join(se.A, "mechanism_table.md")
KAPPA, BW = 2.0, 0.4
LAYOUTS = ("default_A4", "sequential", "clustered", "nmap_greedy", "least_manhattan",
           "heaviest_first", "random", "random_s3", "sa_random_s1")


def boundary_rows(W, pi, kappa):
    base = lw.block_chain(W.cfg, W.S, "prefill", on_chip=True,
                          max_dies=W.fab.level("die").per_parent)
    chain, seating = [], {}
    for li in range(W.cfg.n_layers):
        for e in base:
            n = f"{e['name']}@L{li}"
            chain.append({**e, "name": n})
            seating[n] = list(pi.seat[n])
    fb = lw.block_die_flows(chain, seating, W.fab)
    icl = W.die_ic
    rows = []
    for e in chain[1:]:
        fl = fb[e["name"]]
        load = se.resource_loads(fl, icl, ports=True, kappa=kappa)
        links = {k: v for k, v in load.items() if k[0] != "port"}
        ports = {k: v for k, v in load.items() if k[0] == "port"}
        lmax_k = max(links, key=links.get)
        pmax_k = max(ports, key=ports.get)
        a_b = max(load.values())
        wh = sum(f["volume"] * f["width"] * icl.hops(*f["nodes"]) for f in fl)
        words = sum(f["volume"] * f["width"] for f in fl)
        rows.append({"boundary": e["name"], "type": e["name"].split("@")[0],
                     "words_delivered": words, "word_hops": wh,
                     "mean_hops": wh / words if words else 0.0,
                     "max_link": links[lmax_k], "max_link_key": str(lmax_k),
                     "max_port_over_kappa": ports[pmax_k], "max_port_key": str(pmax_k),
                     "A_b": a_b,
                     "binding": "link" if links[lmax_k] > ports[pmax_k] * (1 + 1e-9)
                     else ("port" if ports[pmax_k] > links[lmax_k] * (1 + 1e-9) else "tie"),
                     "n_flows": len(fl)})
    return rows


def main():
    W = kg.workload((24, 24))
    W.port_ratio = KAPPA
    sweep = json.load(open(os.path.join(se.A, "kappa_geometry_sweep.json")))
    cell = sweep["cells"]["24x24/k2"]
    cands = {"default_A4": ss.pi_from_a4_payload()}
    for n in LAYOUTS:
        if n in kg.RULES:
            cands[n] = sb.generate(n, W, seed=0)
        elif n.startswith("random_s"):
            cands[n] = sb.generate("random", W, seed=int(n.split("_s")[1]))
        elif n.startswith("sa_"):
            cands[n] = ss.Pi.from_json(cell["runs"][n]["best_pi"])
    out = {"note": __doc__.strip(), "kappa": KAPPA, "bw_gbps": BW, "layouts": {}}
    for n, pi in cands.items():
        rows = boundary_rows(W, pi, KAPPA)
        sc = se.score(pi, W, caliber="single", d2d_gbps=BW)
        d = sc.per_phase["prefill"]["decomp"]
        by_type = {}
        for r in rows:
            t = by_type.setdefault(r["type"], {"A": 0.0, "word_hops": 0.0, "n": 0, "link_bound": 0})
            t["A"] += r["A_b"]
            t["word_hops"] += r["word_hops"]
            t["n"] += 1
            t["link_bound"] += r["binding"] == "link"
        hot = sorted(rows, key=lambda r: -r["A_b"])[:3]
        out["layouts"][n] = {
            "T_s": sc.t_opt_s, "layers_s": d["layers_s"], "H_s": d["d2d_serial_s"],
            "propagation_s": d["propagation_s"], "A_words": sum(r["A_b"] for r in rows),
            "A_check_words": d["d2d_busiest_words"],
            "word_hops_total": sum(r["word_hops"] for r in rows),
            "words_delivered_total": sum(r["words_delivered"] for r in rows),
            "mean_hops": sum(r["word_hops"] for r in rows) / sum(r["words_delivered"] for r in rows),
            "n_link_bound": sum(r["binding"] == "link" for r in rows),
            "n_port_bound": sum(r["binding"] == "port" for r in rows),
            "n_tie": sum(r["binding"] == "tie" for r in rows),
            "sum_max_link": sum(r["max_link"] for r in rows),
            "sum_max_port_over_kappa": sum(r["max_port_over_kappa"] for r in rows),
            "by_type": by_type,
            "hotspots": [{k: r[k] for k in ("boundary", "A_b", "binding", "max_link_key", "max_link",
                                             "max_port_over_kappa", "mean_hops")} for r in hot],
            "boundaries": rows}
    json.dump(out, open(OUT, "w"), indent=1)

    L = ["# Mechanism table (S10 task A2): resource loads behind the main-configuration ranking", "",
         f"24×24, κ = {KAPPA:g}, {BW} GB/s, prefill; 159 serial boundaries per layout; loads in words "
         "(ports in link-time units = port words / κ); A = Σ over boundaries of the per-boundary maximum.", "",
         "| layout | T (ms) | H (ms) | A (M words) | total word-hops (G) | mean hops | Σ max link (M) | Σ max port/κ (M) | boundaries link- / port-bound / tie | A by type: qkv / attn / out / ffn1 / ffn2 (M) |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for n in cands:
        r = out["layouts"][n]
        bt = r["by_type"]
        L.append(f"| {n} | {r['T_s']*1e3:.1f} | {r['H_s']*1e3:.1f} | {r['A_words']/1e6:.1f} | {r['word_hops_total']/1e9:.2f} | "
                 f"{r['mean_hops']:.2f} | {r['sum_max_link']/1e6:.1f} | {r['sum_max_port_over_kappa']/1e6:.1f} | "
                 f"{r['n_link_bound']} / {r['n_port_bound']} / {r['n_tie']} | "
                 + " / ".join(f"{bt[t]['A']/1e6:.0f}" if t in bt else "-" for t in ("qkv_proj", "attention", "out_proj", "ffn1", "ffn2")) + " |")
    L += ["", "## Hotspots (top-3 boundaries by A_b per layout)", "",
          "| layout | boundary | A_b (M) | binding | max link (M) @ key | max port/κ (M) | mean hops |", "|---|---|---:|---|---|---:|---:|"]
    for n in cands:
        for h in out["layouts"][n]["hotspots"]:
            L.append(f"| {n} | {h['boundary']} | {h['A_b']/1e6:.2f} | {h['binding']} | {h['max_link']/1e6:.2f} @ {h['max_link_key']} | "
                     f"{h['max_port_over_kappa']/1e6:.2f} | {h['mean_hops']:.2f} |")
    open(MD, "w").write("\n".join(L) + "\n")
    for n in cands:
        r = out["layouts"][n]
        print(f"{n:16} T {r['T_s']*1e3:7.1f} H {r['H_s']*1e3:6.1f} A {r['A_words']/1e6:6.1f}M wh {r['word_hops_total']/1e9:5.2f}G hops {r['mean_hops']:5.2f} "
              f"link/port/tie {r['n_link_bound']}/{r['n_port_bound']}/{r['n_tie']} | by type " +
              " ".join(f"{t[:4]}:{r['by_type'][t]['A']/1e6:.0f}" for t in r["by_type"]))
    print(f"-> {OUT}\n-> {MD}")


if __name__ == "__main__":
    main()
