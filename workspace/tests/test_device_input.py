"""Group 26 -- the device as a fabric input (O17a / C30).

The analog device is the fabric's `device` block: cycle per input bit slice
and slices per MVM row (t_MVM = cycle x slices). Pinned: every shipped
config declares the calibrated wan_nature_2022 device (1.4486 us, 7 slices =
10.14 us per MVM row) and records it in provenance; the run's CiMLoop cycle
(GLOBAL_CYCLE_SECONDS of the macro) equals the declaration and
`verify_cycle` rejects a divergence; the anchor registry's constants ARE the
device's; bandwidths are declared in GB/s and converted at the device cycle
at load (the unit link 12.5 GB/s = 18,107 words/cycle; both units at once
rejected); a faster device changes the words/cycle of a fixed GB/s link but
not the seconds any flow takes on it (the seconds of a link are a GB/s
property -- the invariance the device axis O17b relies on); the functions
that once carried a cycle literal now read the fabric; no `1.449e-6` /
`18112` literal survives in any script.
"""
import dataclasses
import glob
import json
import os
import re
import tempfile

from _util import approx

import scripts.crossbar_comm as cc
from scripts import anchors as an, fabric, placement, traffic

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
CYC = 10.14e-6 / 7


def test_every_shipped_config_declares_the_calibrated_device():
    for p in sorted(glob.glob(os.path.join(WS, "models", "fabric", "*.yaml"))):
        f = fabric.from_yaml(p)
        approx(f.device.cycle_seconds, CYC, 1e-9), p
        assert f.device.input_slices_per_mvm == 7
        approx(f.device.t_mvm_s, 10.14e-6, 1e-9)
        assert "wan_nature_2022" in f.device.name
        pv = fabric.provenance(f)["device"]
        approx(pv["cycle_seconds"], CYC, 1e-9); assert pv["input_slices_per_mvm"] == 7
        approx(pv["t_mvm_s"], 10.14e-6, 1e-9)


def test_the_run_cycle_is_the_declared_device_and_a_divergence_is_rejected():
    """The CiMLoop macro's GLOBAL_CYCLE_SECONDS, as recorded from a real run
    (multidie_placement.json: `cycle_s` = res.cycle_seconds), equals the
    fabric's declaration; verify_cycle is the run-time gate."""
    run_cycle = json.load(open(os.path.join(WS, "analysis", "multidie_placement.json")))["cycle_s"]
    fab = fabric.default()
    approx(run_cycle, fab.device.cycle_seconds, 1e-9)
    fab.verify_cycle(run_cycle)
    try:
        fab.verify_cycle(run_cycle * 1.001)
    except ValueError as e:
        assert "diverged" in str(e)
    else:
        raise AssertionError("a divergent run cycle was accepted")
    for bad in (dict(cycle_seconds=0.0), dict(input_slices_per_mvm=0)):
        try:
            dataclasses.replace(fab, device=dataclasses.replace(fab.device, **bad)).validate()
        except ValueError as e:
            assert "device." in str(e)
        else:
            raise AssertionError(f"{bad} accepted")


def test_the_registry_reads_the_device():
    dev = fabric.default().device
    assert an.CYCLE_S == dev.cycle_seconds and an.T_MVM_S == dev.t_mvm_s
    assert an.SLICES_PER_MVM == dev.input_slices_per_mvm
    approx(an.words_per_cycle(12.5), dev.words_per_cycle(12.5), 1e-12)
    approx(an.gbps_of(dev.words_per_cycle(3.3)), 3.3, 1e-12)
    approx(an.words_per_cycle(1.0, cycle_s=dev.cycle_seconds / 10), an.words_per_cycle(1.0) / 10, 1e-12)
    assert an.as_json()["device"] == dev.name


def test_bandwidths_are_declared_in_gbps_and_converted_at_load():
    fab = fabric.default()
    approx(fab.attention_unit.link_bandwidth_words_per_cycle, 12.5e9 * CYC, 1e-9)   # 18,107.1, not 18,112
    approx(fab.attention_unit.link_bandwidth_words_per_cycle, 18107.14, 1e-5)
    src = open(os.path.join(WS, "models", "fabric", "mlx300.yaml")).read()
    assert "link_bandwidth_gbps: 12.5" in src and "18112" not in src
    # a config with GB/s on a link, a hub and the off-chip port; and a fast device
    y = src.replace("cycle_seconds: 1.4485714285714284e-06", "cycle_seconds: 1.4485714285714284e-07")
    y = y.replace("             reference_hops: 1.0, ns_per_hop: 5.0, calibration: DR-4}",
                  "             reference_hops: 1.0, ns_per_hop: 5.0, calibration: DR-4, bandwidth_gbps: 2.0}\n      hub_bandwidth_gbps: 4.0")
    y = y.replace("  # offchip_bandwidth_gbps: 11.3", "  offchip_bandwidth_gbps: 8.0")
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as t:
        t.write(y)
    f = fabric.from_yaml(t.name)
    c = CYC / 10
    approx(f.device.cycle_seconds, c, 1e-9)
    approx(f.level("macro").link.bandwidth_words_per_cycle, 2.0e9 * c, 1e-9)
    approx(f.level("macro").hub_bandwidth_words_per_cycle, 4.0e9 * c, 1e-9)
    approx(f.offchip_bandwidth_words_per_cycle, 8.0e9 * c, 1e-9)
    approx(f.attention_unit.link_bandwidth_words_per_cycle, 12.5e9 * c, 1e-9)   # 10x fewer words per (shorter) cycle
    # both units at once is an error
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as t2:
        t2.write(y.replace("  offchip_bandwidth_gbps: 8.0", "  offchip_bandwidth_gbps: 8.0\n  offchip_bandwidth_words_per_cycle: 100"))
    try:
        fabric.from_yaml(t2.name)
    except ValueError as e:
        assert "not both" in str(e)
    else:
        raise AssertionError("two units accepted")


def _flows(fab):
    ts = traffic.extract(fabric=fab,
                         mapping_text=open(os.path.join(HERE, "fixtures", "ffn1_prefill_map.txt")).read(),
                         stats_text=open(os.path.join(HERE, "fixtures", "ffn1_prefill_stats.txt")).read())
    ev = ts.edge_volumes()["macro"]
    return [{"level": "glb<->macro", "level_name": "macro", "node": m, "src": "glb", "dst": f"macro{m}",
             "volume": ev["in"] + ev["out"], "down": ev["in"], "up": ev["out"], "distance": 0.0}
            for m in range(8)]


def _with(fab, gbps, topology="mesh", params=None):
    params = {"routing": "xy", "hub": "center"} if params is None else params
    levels = [dataclasses.replace(lv, link=dataclasses.replace(
                  lv.link, topology=topology, params=params,
                  bandwidth_words_per_cycle=fab.device.words_per_cycle(gbps)))
              if lv.name == "macro" else lv for lv in fab.levels]
    return dataclasses.replace(fab, name="t", levels=levels).validate()


def test_seconds_on_a_link_are_a_gbps_property_not_a_device_property():
    """A 10x faster device: the same 2 GB/s link is 10x fewer words per
    cycle, and every flow takes the SAME seconds on it (volume / GB/s); only
    the compute it races changes. This is the invariance the device axis
    (O17b) rests on."""
    slow = fabric.default()
    fast = dataclasses.replace(slow, device=dataclasses.replace(slow.device, cycle_seconds=slow.device.cycle_seconds / 10)).validate()
    approx(fast.device.t_mvm_s, slow.device.t_mvm_s / 10, 1e-12)
    for topology, params in [("star", {}), ("mesh", None), ("bus", {"driver": "center"})]:
        fs, ff = _with(slow, 2.0, topology, params), _with(fast, 2.0, topology, params)
        approx(ff.level("macro").link.bandwidth_words_per_cycle,
               fs.level("macro").link.bandwidth_words_per_cycle / 10, 1e-12)
        os_ = cc.link_occupancy(_flows(fs), fs, fs.device.cycle_seconds, placement.sequential_fill(fs))
        of_ = cc.link_occupancy(_flows(ff), ff, ff.device.cycle_seconds, placement.sequential_fill(ff))
        approx(of_["serialization_s"], os_["serialization_s"], 1e-9)
        for a, b in zip(os_["per_link"], of_["per_link"]):
            assert a["resource"] == b["resource"]
            approx(b["seconds"], a["seconds"], 1e-9)


def test_the_former_literal_sites_read_the_fabric():
    from scripts import llm_workload as lw
    fab = fabric.default()
    cfg = lw.GptConfig()
    u = fab.attention_unit
    a = lw.attention_unit_cost(cfg, 512, "prefill", u)                                  # cycle from the fabric
    b = lw.attention_unit_cost(cfg, 512, "prefill", u, cycle_seconds=fab.device.cycle_seconds)
    approx(a["link_out_s"], b["link_out_s"], 1e-12); approx(a["chain_s"], b["chain_s"], 1e-12)
    st = lw.offload_streams(cfg, 512, "prefill")
    approx(a["link_out_s"], (st["q_out"] + st["kv_out"]) / 12.5e9, 1e-9)              # = words / 12.5 GB/s, whatever the cycle
    ob = dataclasses.replace(fab, offchip_bandwidth_words_per_cycle=fab.device.words_per_cycle(8.0))
    e = lw.embedding_cost(cfg, 512, "prefill", fabric=ob)
    approx(e["latency_s"], 512 * cfg.d_model / 8.0e9, 1e-9)


def test_no_cycle_or_18112_literal_survives_in_any_script():
    for f in sorted(glob.glob(os.path.join(WS, "scripts", "*.py"))):
        src = open(f).read()
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        assert "1.449e-6" not in code and "1.4485714" not in code, f
        assert not re.search(r"\b18112\b|\b1449\b", code), f
