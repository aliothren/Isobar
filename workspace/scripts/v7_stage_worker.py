"""Worker: regenerate named layouts of a record and return their per-hand-off
stage rows as JSON. Run in a subprocess with CIMSIM_FABRIC set to the
record's die variant (the tiler's die menu is fixed at import time), so
rule construction matches the record.

    CIMSIM_FABRIC=... python3 scripts/v7_stage_worker.py <unit> <config_id> <layout> [<layout> ...]
"""
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v6_common as C                      # noqa: E402
from scripts import search_space as ss                  # noqa: E402


def main():
    unit, cid, names = sys.argv[1], sys.argv[2], sys.argv[3:]
    rec = C.find_record(unit, cid); s = rec["spec"]; phase = s["phase"]; bw = float(s["bw"]); kappa = float(s["kappa"])
    W = C.workload_from_record(rec)
    out = {}
    for n in names:
        pi = ss.Pi.from_json(rec["search"]["runs"][n]["best_pi"]) if n in rec["search"]["runs"] else C.candidate_layout(W, n)
        sc, bs = C.evaluate(W, pi, phase, bw)
        out[n] = {"pi": pi.to_json(), "T_s": sc.t_opt_s, "stages": C.stage_rows(W, bs, bw, kappa)}
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
