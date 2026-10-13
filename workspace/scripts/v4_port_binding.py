"""Which resource binds each hand-off of a saved layout at a given port
ratio (link vs injection / ejection port), for the confirmed
configurations' strongest baseline and headline layout.

    python3 scripts/v4_port_binding.py  -> analysis/v4/e3_align/confirm_port_binding.csv
"""
import csv
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import cimsim_cli as cli            # noqa: E402
from scripts import search_baselines as sb       # noqa: E402
from scripts import search_eval as se            # noqa: E402
from scripts import search_space as ss           # noqa: E402
from scripts import v3_sweep as v3               # noqa: E402

OUT = os.path.join(WS, "analysis", "v4", "e3_align", "confirm_port_binding.csv")


def account_for(spec):
    d, dh, ff, S = spec["d"], spec["dh"], spec["d_ff"], spec["S"]
    if (d, dh, ff, S) == (2560, 80, 10240, 512):
        acc = json.load(open(v3.REF_ACCOUNT))
    else:
        acc = json.load(open(os.path.join(v3.V3, "accounts", f"d{d}_dh{dh}_ff{ff}_S{S}.json")))
    acc["config"]["n_layers"] = spec["L"]
    return acc


def main():
    rows = []
    for line in open(os.path.join(v3.V3, "confirm", "configs.jsonl")):
        r = json.loads(line)
        spec = r["spec"]
        fab = v3.make_fabric(tuple(r["grid"]), spec["topology"], spec["routing"])
        W = v3.V3Workload(fab, account_for(spec), ("M", "C")); W.port_ratio = float(spec["kappa"])
        icl = W.die_ic
        layouts = {"strongest:" + r["strongest"]: sb.generate("random", W, seed=int(r["strongest"].split("_s")[1])) if r["strongest"].startswith("random_s") else sb.generate(r["strongest"], W, seed=0),
                   "headline:" + r["search"]["headline"]: ss.Pi.from_json(r["search"]["runs"][r["search"]["headline"]]["best_pi"])}
        for lname, pi in layouts.items():
            for kappa in (1.0, 2.0, 4.0):
                nport = nh = 0; A = 0.0; port_names = []
                for n, fl in cli.handoff_flows(W, pi, spec["phase"]):
                    loads = se.resource_loads(fl, icl, ports=True, kappa=kappa)
                    key = max(loads, key=loads.get); A += loads[key]; nh += 1
                    if key[0] == "port":
                        nport += 1; port_names.append(n.split("@")[0])
                rows.append({"config_id": r["config_id"], "layout": lname, "kappa": kappa, "handoffs": nh, "port_bound_handoffs": nport,
                             "port_bound_ops": ",".join(sorted(set(port_names))), "A_words": A})
        print(r["config_id"][:40], [(x["layout"].split(":")[0], x["kappa"], x["port_bound_handoffs"], x["handoffs"]) for x in rows[-6:]], flush=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("->", OUT)


if __name__ == "__main__":
    main()
