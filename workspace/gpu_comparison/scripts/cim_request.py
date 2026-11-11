"""Full-request cost of a model on a fixed CIM deployment (Table III): one
prefill of L tokens plus O - 1 single-token forwards with the K/V cache
growing, on the stored layout of a deployment record, with the model-end
operators (embedding read, final norm, LM head, argmax) and the digital
attention / K/V costs of the package unit. Static CIM operators, the digital
element-wise work and the hand-off traffic scale exactly with the number of
query rows, so every length is priced from the S = 512 record; the unit's
attention and K/V terms are closed-form per context. Energy is modeled
dynamic energy (no static or idle power in any term); weights are resident
(no programming energy).

    CIMSIM_FABRIC=<die variant> python3 gpu_comparison/scripts/cim_request.py --config gpu_comparison/configs/<id>.json
      -> results/gpu_comparison/cim_requests_<id>.csv, cim_requests_<id>_meta.json
(run_all.sh sets the die variant of each configuration)
"""
import argparse
import copy
import csv
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WS)
from scripts import llm_workload as lw                  # noqa: E402
from scripts import offload as offload_mod              # noqa: E402
from scripts import paths                               # noqa: E402
from scripts import records as C                        # noqa: E402
from scripts import search_eval as se                   # noqa: E402
from scripts import search_space as ss                  # noqa: E402

ME = paths.MODEL_END_COSTS
OUT = os.path.join(paths.RESULTS, "gpu_comparison")


class RequestModel:
    def __init__(self, cfgj):
        self.cfgj = cfgj
        rec = C.find_record(cfgj["record_experiment"], cfgj["config_id"]); self.rec = rec
        spec = rec["spec"]; self.bw = float(cfgj.get("bw_gbps", spec["bw"])); self.kappa = float(spec["kappa"])
        self.Wp = C.workload_from_record(rec)
        rd = copy.deepcopy(rec); rd["spec"]["phase"] = "decode"; self.Wd = C.workload_from_record(rd)
        for W in (self.Wp, self.Wd):
            for k, v in cfgj.get("unit_overrides", {}).items():
                W.offload.unit[k] = v
        self.unit = self.Wp.offload.unit; self.cfg = self.Wp.cfg; self.L = self.cfg.n_layers; self.dig = self.Wp.fab.digital
        run = cfgj.get("layout") or rec["search"]["headline"]
        self.layout = run; self.pi = ss.Pi.from_json(rec["search"]["runs"][run]["best_pi"])
        scp, _ = C.evaluate(self.Wp, self.pi, "prefill", self.bw); scd, _ = C.evaluate(self.Wd, self.pi, "decode", self.bw)
        dp, dd = scp.per_phase["prefill"]["decomp"], scd.per_phase["decode"]["decomp"]
        self.H512, self.Pp, self.Ecomm512 = dp["d2d_serial_s"], dp["propagation_s"], dp["d2d_flat_J"] + dp["d2d_surplus_J"]
        self.Hd, self.Ecommd = dd["d2d_serial_s"] + dd["propagation_s"], dd["d2d_flat_J"] + dd["d2d_surplus_J"]
        self.T512_check = (scp.t_opt_s, rec["search"]["runs"][run]["T_s"] if run in rec["search"]["runs"] else None)
        self.static_p = self.Wp._static_ops("prefill"); self.static_d = self.Wd._static_ops("decode")
        self.me = json.load(open(ME))[cfgj["model"]]
        self.n_hubs = len(self.Wp.offload.hubs) if hasattr(self.Wp.offload, "hubs") else 1
        self.cache = {}
        self.vocab_pad = self.me["lm_head_padded_M"]
        self.lm_pad_scale = self.me["vocab"] / self.vocab_pad if cfgj.get("lm_head_padding_correction", True) else 1.0   # the mapper priced the padded M; the padded columns carry no vocabulary and are not computed
        self.kv_bytes = float(cfgj.get("kv_bytes_per_element", 1))        # K/V element width in bytes (2 = a 16-bit cache)
        gx, gy = rec["grid"]; need = rec["n_dies"] + len(self.Wp.offload.hubs) + self.me["phases"]["decode"]["lm_head"]["dies"] * 8 // cfgj.get("die_macros", 8)
        ext = gx
        while ext * ext < need:
            ext += 1
        self.extended_grid = (ext, ext); self.lm_head_dies = self.me["phases"]["decode"]["lm_head"]["dies"] * 8 // cfgj.get("die_macros", 8); self.slots_needed = need
        self.fits = None
        self.rate_factor = float(cfgj.get("device_rate_factor", 1.0))   # device row rate relative to the NeuRRAM-class reference (10.14 us per row): CIM compute time / factor, energy per operation unchanged

    def set_variant(self, bw=None, rate_factor=None, unit_overrides=None):
        """Re-price the same layout under another mesh bandwidth / device rate / unit parameters (no re-search)."""
        if bw is not None and abs(bw - self.bw) > 1e-12:
            self.bw = float(bw)
            scp, _ = C.evaluate(self.Wp, self.pi, "prefill", self.bw); scd, _ = C.evaluate(self.Wd, self.pi, "decode", self.bw)
            dp, dd = scp.per_phase["prefill"]["decomp"], scd.per_phase["decode"]["decomp"]
            self.H512, self.Pp, self.Ecomm512 = dp["d2d_serial_s"], dp["propagation_s"], dp["d2d_flat_J"] + dp["d2d_surplus_J"]
            self.Hd, self.Ecommd = dd["d2d_serial_s"] + dd["propagation_s"], dd["d2d_flat_J"] + dd["d2d_surplus_J"]
        if rate_factor is not None:
            self.rate_factor = float(rate_factor)
        if unit_overrides:
            for k, v in unit_overrides.items():
                self.unit[k] = v
        self.cache = {}

    # ---- components
    def _elem(self, S, phase):
        ops = [e for e in lw.block_elementwise_ops(self.cfg, S, phase) if e.name not in lw.ATTENTION_ELEMENTWISE]
        cs = [lw.elementwise_cost(e, self.dig) for e in ops]
        return sum(c["latency_s"] for c in cs), sum(c["energy_J"] for c in cs)

    def _rope(self, Pq):
        if not self.cfgj.get("rope", False):
            return 0.0, 0.0
        ops = 3.0 * (self.cfg.n_heads + self.cfg.kv_heads) * self.cfg.dh * Pq      # rotate q and k: per pair 2 mul + 1 add, counted as MAC-equivalents on the unit
        return ops / self.unit["mac_per_second"], ops * self.unit["pj_per_mac"] * 1e-12

    def _model_end(self, phase, n_tokens_in):
        """Per generated token: final norm, LM head (one row, on CIM), its hand-off, argmax; plus the embedding read of the tokens entering this forward."""
        d = self.cfg.d_model; me = self.me["phases"][phase]
        emb_words = n_tokens_in * d
        t_emb = emb_words / self.unit["kv_words_per_second"]; e_emb = emb_words * lw.E_DRAM_PER_WORD_J
        t_pos, e_pos = 0.0, 0.0
        if self.cfgj.get("learned_positions", False):     # OPT: position embedding read and added per token entering
            t_pos = emb_words / self.unit["kv_words_per_second"]; e_pos = emb_words * lw.E_DRAM_PER_WORD_J
            c = lw.elementwise_cost(lw.ElementwiseOp("pos_add", emb_words, 3, adds=1, muls=0, luts=0, after="embedding"), self.dig); t_pos += c["latency_s"]; e_pos += c["energy_J"]
        c = lw.elementwise_cost(lw.ElementwiseOp("final_norm", d, 3, adds=3, muls=2, luts=1.0 / d, after="last_layer"), self.dig); t_norm, e_norm = c["latency_s"], c["energy_J"]
        t_lm, e_lm = me["lm_head"]["compute_s"] / self.rate_factor + me["lm_head"]["write_s"], me["lm_head"]["energy_J"] * self.lm_pad_scale
        n = me["lm_head"]["dies"]; Bw = self.bw * 1e9; Ch = self.unit["link_bandwidth_gbps"] * 1e9
        t_io = max(d / (self.kappa * Bw), (self.vocab_pad / n) / (self.kappa * Bw), self.vocab_pad / Ch, d * n / Ch) + 2 * se.NS_PER_HOP_D2D * 1e-9
        e_io = (d * n + self.vocab_pad) * se.PJ_D2D * 1e-12
        c = lw.elementwise_cost(lw.ElementwiseOp("argmax", self.vocab_pad, 1, adds=1, muls=0, luts=0, after="lm_head"), self.dig); t_arg, e_arg = c["latency_s"], c["energy_J"]
        return {"t_embedding_s": t_emb + t_pos, "e_embedding_J": e_emb + e_pos, "t_final_norm_s": t_norm, "e_final_norm_J": e_norm, "t_lm_head_cim_s": t_lm, "e_lm_head_cim_J": e_lm,
                "t_lm_head_io_s": t_io, "e_lm_head_io_J": e_io, "t_argmax_s": t_arg, "e_argmax_J": e_arg}

    def forward(self, phase, n):
        """phase 'prefill': n = L query rows (context n); 'decode': one row, effective context n after the forward."""
        key = (phase, n)
        if key in self.cache:
            return self.cache[key]
        L = self.L
        if phase == "prefill":
            k = n / 512.0; st = self.static_p; Pq = n; H = self.H512 * k + self.Pp; Ecomm = self.Ecomm512 * k
        else:
            k = 1.0; st = self.static_d; Pq = 1; H = self.Hd; Ecomm = self.Ecommd
        t_cim = sum(o["compute_s"] / self.rate_factor + o["write_s"] for o in st) * k * L; e_cim = sum(o["energy_J"] for o in st) * k * L
        t_el, e_el = self._elem(n, phase); t_el *= L; e_el *= L
        u = offload_mod.unit_layer_cost(self.cfg, n, phase, self.unit, context=n)
        t_uc, t_ukv, e_uc, e_ukv = u["compute_s"] * L, u["kv_s"] * L * self.kv_bytes, u["compute_J"] * L, u["kv_J"] * L * self.kv_bytes
        t_rp, e_rp = self._rope(Pq); t_rp *= L; e_rp *= L
        me = self._model_end(phase, n if phase == "prefill" else 1)
        t_me = sum(v for kk, v in me.items() if kk.startswith("t_")); e_me = sum(v for kk, v in me.items() if kk.startswith("e_"))
        out = {"t_cim_s": t_cim, "t_digital_elementwise_s": t_el, "t_unit_compute_s": t_uc + t_rp, "t_unit_kv_s": t_ukv, "t_comm_s": H, "t_model_end_s": t_me,
               "e_cim_J": e_cim, "e_digital_elementwise_J": e_el, "e_unit_compute_J": e_uc + e_rp, "e_unit_kv_J": e_ukv, "e_comm_J": Ecomm, "e_model_end_J": e_me, **me,
               "algorithm": u["algorithm"]["algorithm"], "n_tiles": u["algorithm"]["n_tiles"]}
        out["t_total_s"] = t_cim + t_el + t_uc + t_rp + t_ukv + H + t_me; out["e_total_J"] = e_cim + e_el + e_uc + e_rp + e_ukv + Ecomm + e_me
        self.cache[key] = out
        return out

    def request(self, Lin, O):
        """T(L, O) = T_prefill(L) + sum_{j=1}^{O-1} T_decode(L + j); energies likewise."""
        keys = ["t_cim_s", "t_digital_elementwise_s", "t_unit_compute_s", "t_unit_kv_s", "t_comm_s", "t_model_end_s", "e_cim_J", "e_digital_elementwise_J", "e_unit_compute_J", "e_unit_kv_J", "e_comm_J", "e_model_end_J", "t_total_s", "e_total_J"]
        p = self.forward("prefill", Lin)
        acc = {k: p[k] for k in keys}; acc_p = dict(acc); acc_d = {k: 0.0 for k in keys}
        for j in range(1, O):
            d = self.forward("decode", Lin + j)
            for k in keys:
                acc[k] += d[k]; acc_d[k] += d[k]
        ctx = Lin + O - 1
        kv = 2 * ctx * self.L * self.cfg.kv_heads * self.cfg.dh * self.kv_bytes / self.n_hubs
        row = {"input_tokens": Lin, "output_tokens": O, "forwards": O, "max_context": ctx, "kv_bytes_at_max_context_per_unit": kv, "kv_fits": kv <= self.unit["kv_capacity_words"],
               "T_prefill_s": acc_p["t_total_s"], "T_decode_sum_s": acc_d["t_total_s"], "E_prefill_J": acc_p["e_total_J"], "E_decode_sum_J": acc_d["e_total_J"], "T_request_s": acc["t_total_s"], "E_request_J": acc["e_total_J"],
               "E_per_output_token_J": acc["e_total_J"] / O, "decode_algorithm_at_max_context": self.forward("decode", ctx)["algorithm"]}
        for k in keys[:-2]:
            row[k[0].upper() + k[1:] + "_request"] = acc[k]
        for k in keys[:6]:
            row[k[0].upper() + k[1:] + "_decode_sum"] = acc_d[k]
        return row


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--config", required=True); ap.add_argument("--out", default=None); args = ap.parse_args()
    cfgj = json.load(open(args.config))
    out = args.out or os.path.join(paths.ensure(OUT), f"cim_requests_{cfgj['id']}.csv")
    M = RequestModel(cfgj)
    rows = []
    for Lin, cnt in cfgj["lengths"]:
        r = M.request(int(Lin), int(cfgj["output_tokens"])); r.update({"config_id": cfgj["id"], "model": cfgj["model"], "count": cnt}); rows.append(r)
    keys = ["config_id", "model", "count"] + [k for k in rows[0] if k not in ("config_id", "model", "count")]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    tot = sum(c for _, c in cfgj["lengths"])
    Tm = sum(r["T_request_s"] * r["count"] for r in rows) / tot; Em = sum(r["E_request_J"] * r["count"] for r in rows) / tot
    meta = {"id": cfgj["id"], "layout": M.layout, "extended_grid_with_lm_head": M.extended_grid, "lm_head_dies": M.lm_head_dies, "slots_needed": M.slots_needed, "lm_head_padding_scale": M.lm_pad_scale, "kv_bytes_per_element": M.kv_bytes, "T512_check": M.T512_check, "H_prefill_512_s": M.H512, "H_decode_s": M.Hd, "unit": M.unit, "bw_gbps": M.bw, "kappa": M.kappa, "n_cim_dies": M.rec["n_dies"], "grid": M.rec["grid"], "lm_head": M.me["phases"]["decode"]["lm_head"],
            "weighted_mean_T_request_s": Tm, "weighted_mean_E_request_J": Em, "n_requests": tot}
    json.dump(meta, open(out.replace(".csv", "_meta.json"), "w"), indent=1)
    print(f"{cfgj['id']}: layout {M.layout} T512 check {M.T512_check} | mean T {Tm:.3f} s E {Em:.1f} J ({Em / cfgj['output_tokens']:.3f} J/token)")


if __name__ == "__main__":
    main()
