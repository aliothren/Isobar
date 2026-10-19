"""Shared helpers of the figure-data round (Isobar_next_tasks section 2-3):
output directory, code version, CSV writer, and the pricing helpers that
re-price a stored candidate (its per-hand-off components) at any mesh
bandwidth / hub capacity / device rate.
"""
import csv
import json
import math
import os
import subprocess
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v6_common as C               # noqa: E402

V7 = os.path.join(WS, "analysis", "v7")
GEMMA_REF = ("e9_confirm", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1")
NAMED_RULES = ["sequential", "snake", "least_manhattan", "clustered", "nmap_greedy", "heaviest_first", "random"]   # the seven rules of the phase diagram; "random" = random_s0


def code_version():
    try:
        h = subprocess.check_output(["git", "-C", WS, "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", WS, "status", "--porcelain", "--", "scripts"], text=True).strip()
        return h + ("+uncommitted-scripts" if dirty else "")
    except Exception:
        return "unknown"


def write_csv(name, rows, subdir=None):
    d = V7 if subdir is None else os.path.join(V7, subdir)
    os.makedirs(d, exist_ok=True)
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    p = os.path.join(d, name)
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    print(f"  {os.path.relpath(p, WS)}: {len(rows)} rows")
    return p


def write_json(name, obj, subdir=None):
    d = V7 if subdir is None else os.path.join(V7, subdir)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    json.dump(obj, open(p, "w"), indent=1)
    print(f"  {os.path.relpath(p, WS)}")
    return p


def protocol_id(rec):
    s = rec["search"]
    return f"pool{rec['n_random']}_seeds{min(s['seeds'])}-{max(s['seeds'])}_obj{s.get('objective', 't_norm')}"


def record_path(unit):
    return os.path.relpath(os.path.realpath(os.path.join(C.V4, unit, "configs.jsonl")), WS)


def H_of(row, B_gbps, C_hub_words_s):
    """Full communication time of a stored candidate at mesh bandwidth B (die ports at kappa B are inside the stored dport/kappa term) and hub capacity C_hub."""
    Bw = B_gbps * 1e9
    return row["prop_s"] + sum(max(max(l, dp) / Bw, h / C_hub_words_s) for l, dp, h in row["comp"])


def H_limit(row, C_hub_words_s):
    """lim_{B -> inf} H: the hub-bound terms plus propagation."""
    return row["prop_s"] + sum(h / C_hub_words_s for _, _, h in row["comp"])


def H_binding(row, B_gbps, C_hub_words_s):
    Bw = B_gbps * 1e9; n = {"link": 0, "die port": 0, "hub port": 0}
    for l, dp, h in row["comp"]:
        t = (("link", l / Bw), ("die port", dp / Bw), ("hub port", h / C_hub_words_s))
        n[max(t, key=lambda x: x[1])[0]] += 1
    return n


def solve_B(row, target_H, C_hub_words_s, lo=1e-6, hi=1e6, steps=100):
    """The mesh bandwidth at which H_of(row, B) == target_H (H decreasing in B); None if the limit is above the target."""
    if H_limit(row, C_hub_words_s) >= target_H:
        return None
    if H_of(row, lo, C_hub_words_s) < target_H:
        return lo
    for _ in range(steps):
        mid = math.sqrt(lo * hi)
        if H_of(row, mid, C_hub_words_s) > target_H:
            lo = mid
        else:
            hi = mid
    return hi


def library(rec):
    """candidates + search endpoints of a record, with a class label per name."""
    out = {}
    for n, r in rec["candidates"].items():
        out[n] = dict(r, candidate_class=("random" if n.startswith("random_s") else "named rule"))
    for n, r in rec["search"]["runs"].items():
        out[n] = dict(r, candidate_class="search endpoint")
    return out
