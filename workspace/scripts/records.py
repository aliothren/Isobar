"""Deployment records (results/records/<experiment>/configs.jsonl): load a
record, rebuild the workload it was evaluated with, regenerate its
candidate layouts, and evaluate a layout with the per-hand-off detail the
exports need (service time under each resource, the binding resource,
propagation, energy terms).
"""
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import llm_workload as lw           # noqa: E402
from scripts import offload as offload_mod       # noqa: E402
from scripts import placement as pm              # noqa: E402
from scripts import search_baselines as sb       # noqa: E402
from scripts import search_eval as se            # noqa: E402
from scripts import experiment as v3             # noqa: E402
from scripts import paths                        # noqa: E402

RECORDS = paths.RECORDS
EXPORTS = paths.EXPORTS
STAGE = {"attention": "qkv->unit", "out_proj": "unit->out_proj", "ffn1": "out_proj->ffn1", "ffn2": "ffn1->ffn2", "qkv_proj": "ffn2->next qkv"}


def load_records(unit):
    """Every record of one experiment directory (e.g. "reference", "capacity_sweep_m16")."""
    p = os.path.join(RECORDS, unit, "configs.jsonl")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def find_record(unit, config_id):
    for r in load_records(unit):
        if r["config_id"] == config_id:
            return r
    raise KeyError(config_id)


def workload_from_record(rec):
    """The workload (fabric, account, port ratio, tiling, offload) a record was evaluated with."""
    spec = rec["spec"]
    account = json.load(open(spec["account_path"]))
    account = json.loads(json.dumps(account)); account["config"]["n_layers"] = spec["L"]
    fab = v3.make_fabric(tuple(rec["grid"]), spec["topology"], spec["routing"])
    W = v3.AccountWorkload(fab, account, v3.TILINGS[spec["tiling"]])
    W.port_ratio = float(spec["kappa"])
    if spec.get("offload"):
        o = spec["offload"]
        W.offload = offload_mod.build(pm.sequential_fill(fab).slots["die"], spec["L"], position=o.get("position", "center"), K=int(o.get("K", 1)),
                                      resource_mode=o.get("resource_mode", "per_unit"), overrides=o.get("unit"), co_located=bool(o.get("co_located", False)),
                                      split=o.get("split", "layer"))
    return W


def candidate_layout(W, name):
    """Regenerate a named candidate (rules are deterministic at seed 0; random_s{k} at seed k)."""
    if name.startswith("random_s"):
        return sb.generate("random", W, seed=int(name.split("_s")[1]))
    return sb.generate(name, W, seed=0)


def evaluate(W, pi, phase, bw):
    """Score with the per-hand-off components; returns (score, boundaries)."""
    bs = W.boundaries(pi, phase)
    sc = se._assemble(pi, W, {phase: bs}, {phase: 1.0}, "single", bw, 1.0)
    return sc, bs


def stage_rows(W, bs, bw, kappa):
    """Per hand-off: stage type, payload words, service time under each resource, the binding resource(s)."""
    off = W.offload
    C = off.unit["link_bandwidth_gbps"] * 1e9 if off is not None else None
    out = []
    for b in bs:
        op = b["into"].rsplit("@L", 1)[0]
        t_link, t_dport = b["link_words"] / (bw * 1e9), b["dport_words"] / (bw * 1e9)
        t_hub = (b.get("hub_words", 0.0) / C) if C else 0.0
        t = max(t_link, t_dport, t_hub)
        binding = [k for k, v in (("link", t_link), ("die port", t_dport), ("hub port", t_hub)) if v == t and t > 0]
        out.append({"into": b["into"], "layer": int(b["into"].rsplit("@L", 1)[1]), "stage": STAGE.get(op, op), "payload_words": b["words"],
                    "link_max_words": b["link_words"], "die_port_max_words_over_kappa": b["dport_words"], "hub_port_max_words": b.get("hub_words", 0.0),
                    "t_link_s": t_link, "t_die_port_s": t_dport, "t_hub_s": t_hub, "service_s": t, "propagation_s": b["max_hops"] * se.NS_PER_HOP_D2D * 1e-9,
                    "max_hops": b["max_hops"], "binding": "+".join(binding), "surplus_J": b["surplus_J"]})
    return out


def energy_breakdown(W, sc, phase):
    L = W.cfg.n_layers
    d = sc.per_phase[phase]["decomp"]
    cim = sum(r["energy_J"] for r in W._static_ops(phase)) * L
    digital = sum(lw.elementwise_cost(eo, W.fab.digital)["energy_J"] for eo in W._elementwise(phase)) * L
    u = W.unit_terms(phase)
    return {"E_total_J": sc.e_J, "E_cim_J": cim, "E_digital_J": digital, "E_unit_compute_J": (u["compute_J"] * L if u else 0.0), "E_kv_J": (u["kv_J"] * L if u else 0.0),
            "E_interconnect_flat_J": d["d2d_flat_J"], "E_interconnect_surplus_J": d["d2d_surplus_J"]}
