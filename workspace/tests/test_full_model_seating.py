"""Group 47 -- A4 (C62-b): the whole-model static spread measured.

Pins the headline (whole vs block x 32 at four anchors, both axes), the
deviation direction, the two-nature decomposition of the energy
increment (caliber 3.8% vs declared-geometry 96.2% -- the qualified
"~4%" sentence travels with its geometry), the x4 multicast caliber
identity, the pure-serial semantics fence, and the S4 payload with the
16x2 seam example."""
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)


def _load():
    return json.load(open(os.path.join(WS, "analysis", "a4_full_model.json")))


def test_headline_and_direction():
    d = _load()
    lat = d["latency_s"]
    approx(lat["whole"]["12.5GBps"], 1.0348, 1e-3)
    approx(lat["extrapolation"]["12.5GBps"], 1.0218, 1e-3)
    approx(lat["deviation"]["12.5GBps"]["rel"], 0.01274, 2e-3)
    approx(lat["deviation"]["0.1GBps"]["rel"], 0.12036, 2e-3)
    for k, v in lat["deviation"].items():
        assert v["rel"] > 0                     # whole >= extrapolation, every anchor
    approx(d["energy_J"]["whole"], 2.394, 1e-3)
    approx(d["energy_J"]["extrapolation"], 2.351, 1e-3)
    approx(d["energy_J"]["deviation_rel"], 0.0183, 2e-2)


def test_multicast_caliber_identity():
    """The x4 the pre-estimate missed: inter-layer words = 31 boundaries x
    S x d x qkv's 4 consumer dies -- the standing multicast convention,
    exact."""
    d = _load()
    approx(d["d2d"]["inter_layer_words"], 31 * 512 * 2560 * 4, 1e-9)


def test_energy_increment_decomposition():
    """The day-3 ruling executed: the increment split by NATURE -- the
    multicast flat charge is an accounting-caliber correction
    (geometry-free), the inter-layer hop surplus AND the layer-offset
    variation (layer 0 is the one row-tight cluster; later clusters
    straddle row wraps) are products of the DECLARED geometry. Verdict:
    GEOMETRY-DOMINATED (96%), so the ~4% share is cited with its
    geometry attached, never as a bare constant."""
    d = _load()
    dc = d["energy_increment_decomposition"]
    approx(dc["multicast_caliber_part_J"] + dc["geometry_hops_part_J"]
           + dc["layer_offset_variation_J"], dc["increment_J"], 1e-6)
    approx(dc["multicast_caliber_part_J"], 1.63e-3, 2e-2)
    approx(dc["layer_offset_variation_J"], 31.4e-3, 2e-2)
    assert dc["geometry_share_of_increment"] > 0.9
    assert dc["verdict"] == "GEOMETRY-DOMINATED"
    assert "never as a bare constant" in dc["qualified_sentence"]
    assert "DECLARED-GEOMETRY" in dc["qualified_sentence"]
    assert 0.035 < dc["d2d_total_share_of_account"] < 0.045


def test_semantics_and_geometry_fences():
    d = _load()
    assert "forbidden" in d["semantics"]        # never vs pipeline readouts
    assert "PURE SERIAL" in d["semantics"]
    assert "no product basis" in d["geometry"]  # declared, not sourced
    assert "multicast-to-every-consumer-die" in d["account"]


def test_seating_and_seam_payload():
    """The S4 payload: 544 contiguous seats (17/layer x 32) and the 16x2
    seam example the search month re-prices directly."""
    d = _load()
    p = d["seating_s4_payload"]
    assert p["grid"] == [24, 24]
    seats = sorted(s for v in p["map"].values() for s in v)
    assert seats == list(range(544))            # contiguous, no overlap
    assert len(p["map"]) == 32 * 5              # 5 die-sets per layer
    seam = p["seam_example_16x2"]
    assert seam["packages"] == 16 and seam["layers_per_package"] == 2
    assert len(seam["seam_boundaries_after_layer"]) == 15
    assert all(seam["package_of_layer"][str(li)] == li // 2
               for li in range(32)) or all(
        seam["package_of_layer"][li] == li // 2
        for li in seam["package_of_layer"])


def test_columns_are_symmetric():
    """The mid-run caliber fix, pinned: the extrapolation column carries
    its own intra flat + surplus (not flat only), so the deviation is a
    real whole-vs-block difference, not a column asymmetry. Propagation
    is negligible as pre-written."""
    d = _load()
    e_layers = 32 * d["layer_energy_J"]
    assert d["energy_J"]["extrapolation"] > e_layers        # intra terms in
    assert d["d2d"]["propagation_s"] < 1e-4                 # < 0.1 ms
