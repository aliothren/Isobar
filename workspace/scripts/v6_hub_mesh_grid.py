"""Follow-up P2 (section 9.1): the hub x mesh bandwidth grid re-priced from
the stored per-hand-off components of the Gemma central-unit records
(prefill 512 and decode 512), without new searches: for every grid cell
the full H / T of every saved candidate (rules + pool + search endpoints
of the record), the strongest of the saved library, the frozen
representative layout's gain, the binding resource mix, the rule-wise
boundaries and the plateau. Cells that would need an independent search
(a strongest-baseline change, a dominant-resource switch, a gain change
of more than 3 points against the neighbouring cell, or a no-finite-
boundary rule) are flagged for section 9.1's follow-up searches.

    python3 scripts/v6_hub_mesh_grid.py  -> analysis/v6/hub_mesh_grid.csv, hub_mesh_search_checks.csv
"""
import csv
import json
import math
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v6_common as C                       # noqa: E402

HUBS = (0.2, 0.4, 0.8, 1.6, 3.125, 12.5)
MESH = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.5)
NS = 20e-9


def H_of(row, B, Ch, with_bind=False):
    tot, bind = 0.0, {"link": 0, "die port": 0, "hub port": 0}
    for l, dp, h in row["comp"]:
        tl, td, th = l / (B * 1e9), dp / (B * 1e9), h / Ch
        t = max(tl, td, th); tot += t
        if with_bind:
            bind[max((("link", tl), ("die port", td), ("hub port", th)), key=lambda x: x[1])[0]] += 1
    return (tot + row["prop_s"], bind) if with_bind else tot + row["prop_s"]


def B_c(row, R, Ch):
    if H_of(row, 1e9, Ch) > R:
        return None
    lo, hi = 1e-6, 1e6
    for _ in range(80):
        mid = math.sqrt(lo * hi)
        if H_of(row, mid, Ch) > R:
            lo = mid
        else:
            hi = mid
    return hi


def main():
    os.makedirs(C.V6, exist_ok=True)
    rows, checks = [], []
    for ph in ("prefill", "decode"):
        rec = C.find_record("e9_ref", f"gemma7b_{ph}512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1")
        R = rec["N_s"] + rec["F_s"]
        lib = {**rec["candidates"], **{n: r for n, r in rec["search"]["runs"].items()}}
        rules = [n for n in rec["candidates"] if not n.startswith("random_s")]
        rep = rec["search"]["headline"]; base_names = list(rec["candidates"])
        grid = {}
        for Ch in HUBS:
            for B in MESH:
                Chw = Ch * 1e9
                T = {n: R + H_of(lib[n], B, Chw) for n in lib}
                strongest = min(base_names, key=lambda n: T[n])
                Hrep, bind = H_of(lib[rep], B, Chw, with_bind=True)
                bcs = {n: B_c(lib[n], R, Chw) for n in rules}
                fin = [v for v in bcs.values() if v is not None]
                plateau = max(sum(h / Chw for _, _, h in lib[n]["comp"]) + lib[n]["prop_s"] for n in base_names)
                cell = {"phase": ph, "C_hub_gbps": Ch, "B_mesh_gbps": B, "R_s": R, "strongest_saved": strongest, "T_strongest_s": T[strongest], "H_strongest_s": T[strongest] - R,
                        "T_representative_s": T[rep], "H_representative_s": Hrep, "G_frozen_pair": 1 - T[rep] / T[strongest], "eta_frozen_pair": 1 - Hrep / (T[strongest] - R), "r0": (T[strongest] - R) / T[strongest],
                        "binding_link": bind["link"], "binding_die_port": bind["die port"], "binding_hub_port": bind["hub port"],
                        "dominant_resource": max(bind, key=bind.get), "rules_B_minus": min(fin) if fin else "", "rules_B_plus": max(fin) if fin else "", "rules_no_finite": sum(1 for v in bcs.values() if v is None),
                        "plateau_max_H_limit_s": plateau, "region": ("no finite boundary" if not fin else "below" if B < min(fin) else "above" if B > max(fin) else "inside"),
                        "kind": "re-pricing of stored candidates (no search)"}
                grid[(Ch, B)] = cell; rows.append(cell)
        # flags for independent searches
        ref = grid[(12.5, 0.4)]
        for (Ch, B), cell in grid.items():
            reasons = []
            if cell["strongest_saved"] != ref["strongest_saved"]:
                reasons.append("strongest baseline changes")
            if cell["dominant_resource"] != ref["dominant_resource"]:
                reasons.append(f"dominant resource {cell['dominant_resource']}")
            if cell["rules_no_finite"]:
                reasons.append("rule(s) without finite boundary")
            nb = [grid[k] for k in ((Ch, MESH[max(0, MESH.index(B) - 1)]), (HUBS[max(0, HUBS.index(Ch) - 1)], B)) if k != (Ch, B)]
            if any(abs(cell["G_frozen_pair"] - x["G_frozen_pair"]) > 0.03 for x in nb):
                reasons.append("gain moves > 3 points vs a neighbour")
            if reasons:
                checks.append({"phase": ph, "C_hub_gbps": Ch, "B_mesh_gbps": B, "reasons": "; ".join(reasons), "G_frozen_pair": cell["G_frozen_pair"], "dominant_resource": cell["dominant_resource"], "independent_search": "flagged (not run)"})
    with open(os.path.join(C.V6, "hub_mesh_grid.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with open(os.path.join(C.V6, "hub_mesh_search_checks.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(checks[0].keys())); w.writeheader(); w.writerows(checks)
    for ph in ("prefill", "decode"):
        print(ph)
        cells = {(r["C_hub_gbps"], r["B_mesh_gbps"]): r for r in rows if r["phase"] == ph}
        for Ch in HUBS:
            print(f"  C_hub {Ch:6.3f}: " + " ".join(f"B{B:g}:{cells[(Ch,B)]['G_frozen_pair']*100:5.1f}%/{cells[(Ch,B)]['dominant_resource'][:3]}" for B in MESH))
    print("flagged cells:", len(checks), "->", C.V6)


if __name__ == "__main__":
    main()
