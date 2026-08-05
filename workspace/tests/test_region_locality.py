"""Group 6 -- the 17.8% region-placement result, pinned from source.

Pure python (io_study's deterministic floorplan + our adopted metric); runs in
both container (/home/io_study mounted) and host. Pins both headline numbers and
the ffn1->ffn2 example that shows why NN-min misleads.
"""
import os
import sys

from _util import SkipTest, approx

_IO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "io_study", "scripts")


def _die_locality():
    if not os.path.isdir(_IO):
        raise SkipTest("io_study not found (mount/merge pending)")
    sys.path.insert(0, _IO)
    import die_locality
    return die_locality


def _vw_allpair(a, b):
    ds = [abs(ma - mb) + abs(ca - cb) for (ma, ca) in a for (mb, cb) in b]
    return sum(ds) / len(ds)


def _totals(metric):
    dl = _die_locality()
    out = {}
    for order, name in ((dl.SIZE_ORDER, "size"), (dl.DATAFLOW_ORDER, "dataflow")):
        cells = dl.region_cells(order)
        out[name] = sum(metric(cells[p], cells[c]) * v for p, c, v in dl.DATAFLOW)
    return out


def test_volume_weighted_drop_is_17_8_percent():
    t = _totals(_vw_allpair)
    approx(100 * (1 - t["dataflow"] / t["size"]), 17.8, 5e-3)


def test_nn_metric_reads_31_percent():
    dl = _die_locality()
    t = _totals(dl.nn_distance)
    approx(100 * (1 - t["dataflow"] / t["size"]), 31.2, 5e-3)


def test_ffn1_ffn2_shows_why_nn_misleads():
    """touching regions score NN=1 under BOTH orders while their volume-weighted
    mean distance is 3.47 -- the concrete example in the report."""
    dl = _die_locality()
    for order in (dl.SIZE_ORDER, dl.DATAFLOW_ORDER):
        cells = dl.region_cells(order)
        assert dl.nn_distance(cells["ffn1"], cells["ffn2"]) == 1
    cells = dl.region_cells(dl.SIZE_ORDER)
    approx(_vw_allpair(cells["ffn1"], cells["ffn2"]), 3.47, 5e-3)