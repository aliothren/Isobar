"""Group 2 -- K/V write geometry invariants.

Pins the July 2026 bug where decode billed a full cache rewrite (Klen had no
phase split, a 512x energy overcount) while the latency model next to it
already assumed append. Energy (cells) and latency (rows/pulses) must derive
from the ONE append-only geometry in block_ops.
"""
from _util import approx

from scripts import llm_workload as lw

CFG = lw.GptConfig()          # d_model 1024, 16 heads -> dh = 64
DH = CFG.d_model // CFG.n_heads


def _dyn(S, phase):
    ops = {o.name: o for o in lw.block_ops(CFG, S=S, phase=phase)}
    return ops["qk^t"], ops["av"]


def test_prefill_programs_all_tokens():
    for S in (128, 512, 1000):
        qk, av = _dyn(S, "prefill")
        assert qk.write_cells == DH * S * CFG.n_heads
        assert av.write_cells == DH * S * CFG.n_heads
        assert qk.write_rows == DH          # K^T: dh wordlines regardless of S
        assert av.write_rows == S           # V: one wordline per token


def test_decode_appends_one_token():
    for S in (128, 512, 1000):
        qk, av = _dyn(S, "decode")
        assert qk.write_cells == DH * CFG.n_heads, "decode must NOT rebill the cache"
        assert av.write_cells == DH * CFG.n_heads
        assert qk.write_rows == DH          # a new COLUMN: dh distinct wordlines
        assert av.write_rows == 1           # a new ROW: one wordline


def test_energy_ratio_is_S():
    S = 512
    pre_q, pre_a = _dyn(S, "prefill")
    dec_q, dec_a = _dyn(S, "decode")
    assert (pre_q.write_cells + pre_a.write_cells) \
        == S * (dec_q.write_cells + dec_a.write_cells)


def test_latency_ratio_is_about_5x_at_S512():
    """energy drops 512x but latency only ~5x -- the axis asymmetry."""
    S = 512
    pre = sum(lw.write_latency_s(o, "prefill") for o in _dyn(S, "prefill"))
    dec = sum(lw.write_latency_s(o, "decode") for o in _dyn(S, "decode"))
    exp_pulses_pre = min(DH, lw.CIM_ROWS) + min(S, lw.CIM_ROWS)      # 64 + 256
    exp_pulses_dec = min(DH, lw.CIM_ROWS) + 1                        # 64 + 1
    approx(pre, exp_pulses_pre * lw.T_SET_NS * 1e-9, 1e-9)
    approx(dec, exp_pulses_dec * lw.T_SET_NS * 1e-9, 1e-9)
    approx(pre / dec, exp_pulses_pre / exp_pulses_dec, 1e-9)         # ~4.92x


def test_row_serial_cap():
    _, av = _dyn(10_000, "prefill")
    assert min(av.write_rows, lw.CIM_ROWS) == lw.CIM_ROWS, \
        "rows beyond CIM_ROWS must tile onto parallel crossbars"
    assert lw.write_latency_s(av, "prefill") == lw.CIM_ROWS * lw.T_SET_NS * 1e-9


def test_static_ops_never_write():
    for phase in ("prefill", "decode"):
        for o in lw.block_ops(CFG, S=512, phase=phase):
            if o.kind == "static":
                assert o.write_cells == 0 and o.write_rows == 0
                assert lw.write_latency_s(o, phase) == 0.0