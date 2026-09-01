"""Group 29 -- the T1 (die-buffer) bandwidth axis audited (O28 / C34).

Pins: (1) the unit audit -- Timeloop's native glb throttling charges COUNTER
units, not value words: for ffn1 the write port binds at 7*S*C (input fills,
bit slices) + 2*8*S*M (output fills + updates, bit groups) = 37,224,448
units, and every cached Timeloop point equals write-units / bandwidth
EXACTLY -- the "160x at 64 w/c" anomaly reproduced and explained (C25's
sibling on the T1 axis); (2) the analytic T1 axis in value units: per matmul
op, hub words = the T2 bus words + the op's input tensor arriving into the
buffer once (P x C x N) -- an identity on stored components, so the T1
boundary is the bus boundary shifted by the in-fill share (ffn1 +6.25%);
(3) the thresholds and the MX100-class reading (DMA + shared SRAM = one
shared port = THIS axis): 1% at 2.27 / 2.33 GB/s (prefill), busiest-op
net = compute at 2.42 GB/s; at the estimated band's low end (0.4 GB/s)
3.9-5.0x, at its high end 1.00x; (4) no shipped config declares a hub
bandwidth, so the counter-unit Timeloop push stays inert (validation only);
(5) decode-offloaded equals prefill-offloaded exactly -- S cancels in every
hub ratio, the same identity group 28 measured on the wires.
"""
import glob
import json
import os

from _util import approx

from scripts import anchors as an, fabric, llm_workload as lw

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
SWEEP = json.load(open(os.path.join(WS, "analysis", "phase_sweep.json")))
T1 = SWEEP["t1_hub"]
CYC = an.CYCLE_S
REF_WC = SWEEP["fixed"]["ref_words_per_cycle"]


def test_timeloop_glb_throttling_is_in_counter_units():
    """The cached Timeloop points (bandwidth_sweep_t1.json) equal the
    write-port counter units / bandwidth exactly: input fills x7 bit
    slices + output fills AND updates x8 bit groups. The write side binds
    (37.2M > the read side's 20.4M); against the ~8.9M value-unit hub
    words that is a ~4.2x unit inflation -- the 160x-at-64-w/c anomaly."""
    S, C, M = 512, 1024, 4096
    write_units = 7 * S * C + 2 * 8 * S * M
    read_units = 7 * S * C + 8 * S * M
    assert write_units == 37224448 and write_units > read_units
    rows = json.load(open(os.path.join(WS, "analysis", "bandwidth_sweep_t1.json")))
    assert [r["bw"] for r in rows] == [64.0, 16.0, 4.0, 1.0]
    for r in rows:
        approx(r["compute_s"], write_units / r["bw"] * CYC, 1e-9)
    # the anomaly as once reported: 160x the 5.19 ms co-residency compute
    assert 155 < rows[0]["compute_s"] / 5.192e-3 < 165
    # value-unit hub words for the same op (bus + in-fill): ~4.2x fewer
    hub = T1["conditions"]["prefill, attention on chip"]["per_op"]["ffn1"]
    hub_words = hub["hub_serial_ref_s"] / CYC * REF_WC
    assert 4.0 < write_units / hub_words < 4.4


def test_hub_equals_bus_plus_the_input_fill():
    """The identity behind the axis: per matmul op, hub seconds at the
    reference = the stored bus seconds + P x C x N values through the port
    once. ffn1's in-fill share is +6.25% (S*C over 8*S*C + 2*S*M)."""
    cfg = lw.GptConfig()
    for title, cond in T1["conditions"].items():
        phase = "prefill" if "prefill" in title else "decode"
        shapes = {o.name: o.P * o.C * o.N for o in lw.block_ops(cfg, 512, phase)}
        for name, v in cond["per_op"].items():
            if v["kind"] == "elementwise":
                assert v["hub_serial_ref_s"] == 0.0
                continue
            approx(v["infill_ref_s"], shapes[name] * CYC / REF_WC, 1e-12)
            approx(v["hub_serial_ref_s"], v["bus_serial_ref_s"] + v["infill_ref_s"], 1e-12)
            assert v["hub_serial_ref_s"] > v["bus_serial_ref_s"]
    pre = T1["conditions"]["prefill, attention on chip"]["per_op"]
    approx(pre["ffn1"]["infill_ref_s"] / pre["ffn1"]["bus_serial_ref_s"], 0.0625, 1e-9)
    approx(pre["ffn2"]["infill_ref_s"] / pre["ffn2"]["bus_serial_ref_s"], 0.20, 1e-9)


def test_t1_thresholds_and_the_mx100_class_reading():
    """The axis readout: knee ffn2 in every condition; 1% at 2.27 (prefill
    on chip, vs the T2 bus's 1.89 -- the in-fill shift) / 2.33 (offloaded);
    busiest-op net = compute at 2.42 GB/s. MX100-class chips (tier bus-T1
    in the registry) read here: 3.9-5.0x at the estimated band's low end,
    1.00x at its high end."""
    for title, cond in T1["conditions"].items():
        assert cond["knee_op"] == "ffn2", title
        approx(cond["thresholds_gbps"]["busiest_op_net_eq_comp"], 2.42, 1e-2)
    on = T1["conditions"]["prefill, attention on chip"]
    off = T1["conditions"]["prefill, attention offloaded"]
    approx(on["thresholds_gbps"]["max_1pct"], 2.27, 1e-2)
    approx(off["thresholds_gbps"]["max_1pct"], 2.33, 1e-2)
    bus_1pct = SWEEP["ondie"]["conditions"]["prefill, attention on chip"][
        "schemes"]["bus (shared medium)"]["thresholds_gbps"]["max_1pct"]
    assert on["thresholds_gbps"]["max_1pct"] > bus_1pct          # the in-fill shift
    approx(on["columns"]["analog_ondie_low"]["max"], 3.94, 1e-2)
    approx(off["columns"]["analog_ondie_low"]["max"], 4.06, 1e-2)
    approx(on["columns"]["analog_ondie_high"]["max"], 1.00, 5e-3)
    assert an.chip("mx100").tier == "bus-T1"
    # decode-offloaded == prefill-offloaded: S cancels in every hub ratio
    dec = T1["conditions"]["decode, attention offloaded"]
    for k in ("max_1pct", "max_2x"):
        approx(dec["thresholds_gbps"][k], off["thresholds_gbps"][k], 1e-9)


def test_no_shipped_config_declares_a_hub_bandwidth():
    """The Timeloop push (mlx_system) consumes counter units, so it must
    stay inert in shipped configs: the fabric-declared hub bandwidth (value
    units) feeds the ANALYTIC axis only."""
    for p in sorted(glob.glob(os.path.join(WS, "models", "fabric", "*.yaml"))):
        f = fabric.from_yaml(p)
        for lv in f.levels:
            assert lv.hub_bandwidth_words_per_cycle is None, (p, lv.name)
