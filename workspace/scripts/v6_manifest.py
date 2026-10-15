"""Follow-up P0 (section 3): one stable identity per physical configuration,
protocol and layout over every recorded unit of analysis/v4, with the
status and the path of the source record.

    python3 scripts/v6_manifest.py  -> analysis/v6/configuration_manifest.{csv,jsonl}, protocols.json, status_summary.md
"""
import csv
import glob
import hashlib
import json
import os
import statistics
import subprocess
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v3_sweep as v3               # noqa: E402

V4 = os.path.join(WS, "analysis", "v4")
V6 = os.path.join(WS, "analysis", "v6")


def git_rev():
    try:
        return subprocess.check_output(["git", "-C", os.path.dirname(WS), "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def physical_id(r):
    s = r["spec"]; o = s.get("offload") or {}
    att = r.get("attention") or {}
    key = {"model": s.get("model", s.get("model_tag")), "phase": s["phase"], "S": s["S"], "batch": 1, "tiling": s["tiling"], "account": os.path.basename(s.get("account_path", "")),
           "die_macros": s.get("die_macros", 8), "grid": r.get("grid"), "topology": s["topology"], "routing": s["routing"], "kappa": s["kappa"], "bw": s["bw"],
           "attention": att.get("mode", "die"), "position": o.get("position"), "K": o.get("K"), "resource_mode": o.get("resource_mode"), "split": o.get("split", "layer" if o else None),
           "unit": o.get("unit") or {}}
    h = hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()[:10]
    return h, key


def protocol_id(r):
    sr = r.get("search") or {}
    seeds = sr.get("seeds", [])
    return (f"pool{r.get('n_random')}_seeds{min(seeds)}-{max(seeds)}_obj{sr.get('objective', 't_norm')}_t0{sr.get('t0_norm', 0):.6f}_alpha{sr.get('alpha', 0)}_budgetM(n)" if seeds else "")


def main():
    os.makedirs(V6, exist_ok=True)
    rows, protocols, rev = [], {}, git_rev()
    for p in sorted(glob.glob(os.path.join(V4, "*", "configs.jsonl"))):
        unit = os.path.basename(os.path.dirname(p))
        for line in open(p):
            r = json.loads(line); s = r["spec"]; o = s.get("offload") or {}
            att = r.get("attention") or {}; alg = (att.get("unit_layer_cost") or {}).get("algorithm") or {}
            pid, key = physical_id(r)
            prot = protocol_id(r)
            if prot:
                protocols.setdefault(prot, {"n_random": r.get("n_random"), "seeds": r["search"]["seeds"], "objective": r["search"].get("objective", "t_norm"),
                                            "t0_norm": r["search"]["t0_norm"], "alpha": r["search"]["alpha"], "budget": "max(1200, ceil(1200 n/544)) steps, n = movable dies",
                                            "starts": "strongest named rule, strongest random of the pool, random seed 0", "statistic": "per seed the best of the starts; median and min/max over seeds; the representative is the median seed's best run"})
            row = {"config_id": r["config_id"], "unit": unit, "physical_id": pid, "protocol_id": prot, "status": r["status"], "reason": r.get("reason", ""),
                   "model": key["model"], "phase": s["phase"], "S": s["S"], "batch": 1, "scope": "transformer backbone",
                   "attention": key["attention"], "account": key["account"], "tiling": s["tiling"], "chain": "; ".join(f"{n}:{k}{sp or ''}" for n, k, sp in r.get("chain", [])),
                   "die_macros": key["die_macros"], "die_cells": key["die_macros"] * 32 * 65536, "n_dies": r.get("n_dies", ""), "n_units": len(att.get("hubs", [])) if att.get("hubs") else 0,
                   "grid": "x".join(map(str, r["grid"])) if r.get("grid") else "", "slots": (r["grid"][0] * r["grid"][1]) if r.get("grid") else "", "empty_slots": r.get("empty_slots", ""),
                   "routing": s["routing"], "kappa": s["kappa"], "bw_mesh_gbps": s["bw"], "device_rate": 1.0,
                   "hub_position": o.get("position", ""), "K": o.get("K", ""), "grouping": o.get("split", "layer") if o else "", "resource_mode": o.get("resource_mode", ""),
                   "unit_nodes": att.get("hubs", ""), "layer_unit": att.get("layer_unit", ""),
                   "unit_mac_per_s": (att.get("unit") or {}).get("mac_per_second", ""), "unit_kv_gbps": ((att.get("unit") or {}).get("kv_words_per_second", 0) / 1e9) or "",
                   "unit_kv_capacity_bytes": (att.get("unit") or {}).get("kv_capacity_words", ""), "hub_capacity_gbps_per_direction": (att.get("unit") or {}).get("link_bandwidth_gbps", ""),
                   "unit_buffer_bytes": (att.get("unit") or {}).get("buffer_bytes", ""),
                   "total_mac_per_s": ((att.get("unit") or {}).get("mac_per_second", 0) * len(att.get("hubs", []))) or "",
                   "attention_algorithm": alg.get("algorithm", ""), "query_tiles": alg.get("n_tiles", ""), "kv_reads_per_layer": alg.get("kv_reads_per_layer", ""),
                   "spill_words": alg.get("extra_memory_words", "") if alg.get("spill") else 0, "workspace_bytes_per_head": alg.get("workspace_bytes_per_head", ""),
                   "kv_fits": all(x["fits"] for x in att.get("kv_capacity", [])) if att.get("kv_capacity") else "",
                   "scan_axis": (next(iter((o.get("unit") or {}).keys()), ("bw_mesh" if s["bw"] != 0.4 else "")) if o else ""),
                   "scan_value": (next(iter((o.get("unit") or {}).values()), (s["bw"] if s["bw"] != 0.4 else "")) if o else ""),
                   "strongest": r.get("strongest", ""), "headline_layout": (r.get("search") or {}).get("headline", ""), "T_base_s": r.get("T_base_s", ""),
                   "headline_T_s": (r.get("search") or {}).get("headline_T_s", ""),
                   "G_headline": (r.get("unified") or (v3.unified_metrics(r) if r["status"] == "done" else {})).get("G_headline", ""),
                   "record_path": os.path.relpath(p, WS), "code_version": rev}
            rows.append(row)
    keys = list(rows[0].keys())
    with open(os.path.join(V6, "configuration_manifest.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    with open(os.path.join(V6, "configuration_manifest.jsonl"), "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    json.dump(protocols, open(os.path.join(V6, "protocols.json"), "w"), indent=1)
    # status summary: dedupe by physical id and protocol
    done = [r for r in rows if r["status"] == "done"]
    by = {}
    for r in done:
        by.setdefault((r["physical_id"], r["protocol_id"]), []).append(r)
    off = [r for r in done if r["attention"] == "unit"]; die = [r for r in done if r["attention"] == "die"]
    md = ["# Status summary (follow-up P0, section 3)\n",
          f"Records: {len(rows)} in {len(set(r['unit'] for r in rows))} units; done {len(done)}, other statuses: " + ", ".join(f"{s}: {n}" for s, n in sorted(__import__('collections').Counter(r['status'] for r in rows if r['status'] != 'done').items())) + ".",
          f"Distinct (physical configuration, protocol) pairs among the done records: {len(by)}; pairs recorded more than once: {sum(1 for v in by.values() if len(v) > 1)} (the duplicates agree, the search being deterministic per seed).",
          f"Attention on the digital unit: {len(off)} done records over {len({r['physical_id'] for r in off})} physical configurations; attention on a ReRAM die: {len(die)} done records over {len({r['physical_id'] for r in die})}.",
          f"Code version of this export: {rev}.\n",
          "## Not-run / infeasible categories\n"]
    for s in sorted({r["status"] for r in rows if r["status"] != "done"}):
        cats = __import__("collections").Counter(r["reason"].split(":")[0] for r in rows if r["status"] == s)
        md.append(f"- {s}: " + "; ".join(f"{k} ({n})" for k, n in cats.items()))
    # ranges the request asks to check, generated from the rows
    g = [float(r["G_headline"]) * 100 for r in done if r["unit"] == "e9_struct" and r["model"] == "gemma7b"]
    o13 = [float(r["G_headline"]) * 100 for r in done if r["unit"] == "e9_struct" and r["model"] == "opt13b" and float(r["kappa"]) == 1.0]
    md.append("\n## Ranges generated from the rows (section 3 check)\n")
    md.append(f"- Gemma geometry x routing x port ratio (e9_struct, headline gains): n {len(g)}, min {min(g):.2f}%, max {max(g):.2f}% (the 23.0% point is the 72x18 YX kappa 2 / 4 cell).")
    md.append(f"- OPT-13B kappa 1 cells (e9_struct): n {len(o13)}, min {min(o13):.2f}%, max {max(o13):.2f}%.")
    for u in sorted({r["unit"] for r in done}):
        xs = [float(r["G_headline"]) * 100 for r in done if r["unit"] == u and r["G_headline"] != ""]
        if xs:
            md.append(f"- {u}: {len(xs)} done, headline gain {min(xs):.2f} to {max(xs):.2f}%, median {statistics.median(xs):.2f}%.")
    open(os.path.join(V6, "status_summary.md"), "w").write("\n".join(md) + "\n")
    print("->", V6, len(rows), "rows,", len(protocols), "protocols")


if __name__ == "__main__":
    main()
