"""Group 8 -- analytic workload models vs independent hand-derived sums.

decode_kv_cost and die_to_die_activation are closed-form; recompute them here
with straight loops so the code's algebra is checked against the definition,
not against itself.
"""
from _util import approx

from scripts import llm_workload as lw

CFG = lw.GptConfig()          # d=1024, L=24


def test_kv_cost_matches_definition():
    G, d, L = 300, CFG.d_model, CFG.n_layers
    kv = lw.decode_kv_cost(CFG, G)
    read = sum(2 * t * d for t in range(1, G + 1)) * L      # attend whole cache
    write = 2 * d * G * L                                    # append per step
    assert kv["read_words"] == read
    assert kv["write_words"] == write
    approx(kv["read_energy_J"], read * lw.E_DRAM_PER_WORD_J, 1e-12)
    approx(kv["kv_total_J"], (read + write) * lw.E_DRAM_PER_WORD_J, 1e-12)


def test_kv_read_is_quadratic_write_linear():
    a, b = lw.decode_kv_cost(CFG, 500), lw.decode_kv_cost(CFG, 1000)
    approx(b["write_words"] / a["write_words"], 2.0, 1e-12)          # ~G
    ratio = b["read_words"] / a["read_words"]                        # ~G^2
    assert 3.9 < ratio < 4.01, f"read scaling {ratio}, expected ~4"


def test_kv_cache_footprint():
    assert lw.kv_cache_size_bytes(CFG, 512, dtype_bytes=2) \
        == 2 * 512 * CFG.d_model * CFG.n_layers * 2


def test_die_to_die_word_counts():
    for phase, tokens in (("prefill", 512), ("decode", 1)):
        d2d = lw.die_to_die_activation(CFG, S=512, phase=phase, chip2chip_pJ=5.0)
        assert d2d["words"] == tokens * CFG.d_model * (CFG.n_layers - 1)
        assert d2d["n_boundaries"] == CFG.n_layers - 1


def test_single_layer_has_zero_d2d():
    """the model-level miniature of the single-die degeneracy invariant."""
    cfg1 = lw.GptConfig(n_layers=1)
    d2d = lw.die_to_die_activation(cfg1, S=512, phase="prefill", chip2chip_pJ=5.0)
    assert d2d["words"] == 0
    assert d2d["energy_J"] == 0.0
    assert d2d["latency_s"] == 0.0