"""The anchor registry (O25): the single source of every published bandwidth
this repository reads its threshold curves at, of the analog-reality tier,
and of the real-system CHIP POINTS the phase diagram (O29) draws.

Identity. Every measured / post-layout bandwidth here is a DIGITAL
accelerator's link (Simba, ESP and FlooNoC NoCs on die; Simba's GRS package
mesh die to die): the upper bound of what fabricated interconnects deliver,
not the operating point of an analog CIM chip (UCIe-S 64 is one step
further out: an interconnect STANDARD's ceiling, status `spec`, C40).
One analog system DOES now
publish a link rate (C36, 2026-09-01): HERMES's chip spec table gives a
maximum link data-rate of 3.2 Gbit/s = 0.4 GB/s per link -- landing exactly
on the analog-reality band's LOW end; the band stays the CLASS estimate,
the HERMES chip point carries the published value. A readout against the
digital anchors is
the digital-ecosystem column of the phase diagram (model scale x device speed
x transfer paradigm x link tier). The analog-reality tier is a structural
ESTIMATE, carried as a band with `status = "estimated"`, until a chip's own
values arrive (platform input DR-2).

Units. Bandwidths are declared in GB/s (1 word = one 8-bit value) and
converted to the simulator's words per device cycle with the FABRIC'S DEVICE
(O17a / C30): `fabric.default().device` -- the calibrated wan_nature_2022
macro in the shipped configs, 10.14 us per MVM row over 7 input bit slices =
1.4486 us per slice. CYCLE_S / T_MVM_S / SLICES_PER_MVM below are that
device's numbers, not constants of their own; a fabric with another device
(CIMSIM_FABRIC) re-labels every anchor consistently. Nothing that prints an
anchor may define its own bandwidth constant; `tests/test_anchor_registry.py`
checks.

Paradigm -> model tier. A DMA engine with shared SRAM (MX100 class) is a
shared medium whose bandwidth is a T1 number in this model (the die buffer's
`hub_bandwidth_words_per_cycle`), not a T2 link; a compile-time scheduled
point-to-point fabric (Mythic, HERMES) is the star scheme; a network-on-chip
(the digital anchors) is the routed mesh.
"""
import os
import sys
from dataclasses import dataclass, asdict
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # `scripts` as a package when run directly

# ----------------------------------------------------------------- units
from scripts import fabric as _fabric                # noqa: E402

DEVICE = _fabric.default().device                   # the fabric's device: the one source (O17a)
SLICES_PER_MVM = DEVICE.input_slices_per_mvm        # signed 8-bit inputs, encoded (7)
T_MVM_S = DEVICE.t_mvm_s                            # per MVM row (10.14 us, NeuRRAM class)
CYCLE_S = DEVICE.cycle_seconds                      # per input bit slice (1.4485714e-6)


def words_per_cycle(gbps: float, cycle_s: float = None) -> float:
    """GB/s -> words per device cycle (1 word = 8 bits); the fabric's device
    cycle unless another is given (the device axis, O17b)."""
    return gbps * 1e9 * (CYCLE_S if cycle_s is None else cycle_s)


def gbps_of(wc: float, cycle_s: float = None) -> float:
    """words per device cycle -> GB/s."""
    return wc / (1e9 * (CYCLE_S if cycle_s is None else cycle_s))


WC_PER_GBPS = words_per_cycle(1.0)                  # 1,448.6 words/cycle per GB/s

DIGITAL = "digital-ecosystem"
ANALOG = "analog-reality"
ONDIE, D2D = "ondie", "d2d"


# ----------------------------------------------------------------- anchors
@dataclass(frozen=True)
class Anchor:
    key: str
    label: str            # short, for tables and figure legends
    level: str            # ONDIE | D2D
    paradigm: str         # DIGITAL | ANALOG
    status: str           # measured | post-layout | secondary | spec | estimated
    source: str
    gbps: Optional[float] = None                 # a point ...
    band: Optional[Tuple[float, float]] = None   # ... or a band (low, high)
    derivation: str = ""

    @property
    def values(self):
        """The GB/s values this anchor contributes to a readout column set."""
        return (self.gbps,) if self.gbps is not None else tuple(self.band)

    def words_per_cycle(self, cycle_s: float = None):
        return tuple(words_per_cycle(g, cycle_s) for g in self.values)


ANCHORS = [
    Anchor("simba_ondie", "Simba 8.75", ONDIE, DIGITAL, "measured",
           "Zimmer et al., JSSC 2020 (Simba, 16 nm): 'each link of the NoC achieves 70-Gb/s bandwidth' at 0.72 V",
           gbps=8.75),
    Anchor("esp", "ESP 32", ONDIE, DIGITAL, "measured",
           "Jia et al., ESSCIRC 2022 (12nm ESP-based SoC): 5 data NoC planes x 64 bit + "
           "1 control plane x 32 bit, NoC measured at 800 MHz; tile-to-tile max 281 Gb/s "
           "(the paper's headline, all 6 planes)",
           gbps=32.0,
           derivation="the 5 data planes: 5 x 64 bit x 800 MHz = 256 Gb/s = 32 GB/s tile-to-tile "
                      "(the quantity FlooNoC's comparison quotes); one physical plane alone is "
                      "6.4 GB/s -- multi-plane aggregate, stated as such (C36)"),
    Anchor("floonoc", "FlooNoC 80.6", ONDIE, DIGITAL, "post-layout",
           "Fischer et al., FlooNoC, arXiv:2409.17606: 645 Gb/s per link, 12 nm post-layout",
           gbps=80.6),
    Anchor("grs", "GRS 12.5", D2D, DIGITAL, "measured",
           "Zimmer et al., JSSC 2020: Simba package mesh, 100 Gb/s per link direction (GRS)",
           gbps=12.5,
           derivation="the demonstrated-MAXIMUM mode (25 Gb/s/pin x 4 lanes). Simba's own "
                      "placement experiments ran the 11 Gb/s mode = 5.5 GB/s per direction "
                      "(SIMBA_EXPERIMENT_GRS_GBPS below; MICRO'19 §4.1) -- an operating "
                      "point, not a capability line; neither number corrects the other (C41)"),
    Anchor("ucie", "UCIe-S 64", D2D, DIGITAL, "spec",
           "UCIe Consortium specification (uciexpress.org): STANDARD-package module, "
           "x16 lanes at 32 GT/s per lane -- an interconnect STANDARD's raw signaling "
           "ceiling (no protocol overhead deducted), not a measured chip; no per-link "
           "silicon measurement is in the registry yet -- revisit when one publishes "
           "(C40, amended C40-r)",
           gbps=64.0,
           derivation="16 lanes x 32 GT/s = 512 Gb/s = 64 GB/s per direction per module. "
                      "Standard package chosen DELIBERATELY: organic substrate, the "
                      "packaging class of Simba's GRS and of plausible analog-CIM "
                      "packages (the advanced-package x64 module reaches 256 GB/s -- "
                      "noted, not adopted). Mapping convention, stated like the HERMES "
                      "aggregation rule: ONE UCIe module = one model die-link; a real "
                      "design may gang several modules per edge"),
    Anchor("analog_ondie", "analog on-die 0.4-8", ONDIE, ANALOG, "estimated",
           "structural estimate of the class; the one published analog link rate "
           "(HERMES 0.4 GB/s, C36) lands on this band's low end",
           band=(0.4, 8.0),
           derivation="a 32-128-bit datapath at 100-500 MHz (65-130 nm digital periphery): "
                      "32 bit x 100 MHz = 0.4 GB/s .. 128 bit x 500 MHz = 8 GB/s"),
    Anchor("analog_d2d", "analog D2D 0.1-2", D2D, ANALOG, "estimated",
           "structural estimate: board-level or older-node direct chip-to-chip links",
           band=(0.1, 2.0),
           derivation="GPIO / LVDS-class links (8-32 lanes x 100-500 Mb/s) to a short SerDes-free "
                      "parallel link: 0.1 .. 2 GB/s per direction"),
]


# Operating-point data of the Simba REPRODUCTION preset (C41, worklist step
# 1) -- deliberately NOT Anchor rows: readout columns are capability anchors,
# and adding these would silently widen every sweep. The reproduction's
# fabric (models/fabric/simba.yaml) freezes these values; provenance:
# analysis/papers/simba_extracts.md.
SIMBA_EXPERIMENT_GRS_GBPS = 5.5    # 4 GRS lanes x 11 Gb/s mode (MICRO'19 §4.1)
SIMBA_EXPERIMENT_NOC_GBPS = 8.75   # 70 Gb/s per NoC link at 0.72 V (JSSC'20 §II-C)
SIMBA_EXPERIMENT_PE_HZ = 1.03e9    # PE clock at the experiment point (MICRO'19 §4.1)
SIMBA_MACS_PER_CHIPLET_CYCLE = 1024  # 16 PEs x 8 vector MACs x 8-wide (Tab 2)


def by_key(key: str) -> Anchor:
    for a in ANCHORS:
        if a.key == key:
            return a
    raise KeyError(key)


def digital(level: str):
    """The digital-ecosystem anchors of a level, in ascending bandwidth."""
    return sorted((a for a in ANCHORS if a.level == level and a.paradigm == DIGITAL),
                  key=lambda a: a.gbps)


def band(level: str) -> Anchor:
    """The analog-reality band of a level."""
    return next(a for a in ANCHORS if a.level == level and a.paradigm == ANALOG)


def columns(level: str):
    """Readout columns for a level: the digital anchors as points plus the two
    ends of the analog-reality band -- every sweep prints both paradigms.
    Returns [(column_key, label, gbps, paradigm, status)]."""
    cols = [(a.key, a.label, a.gbps, a.paradigm, a.status) for a in digital(level)]
    b = band(level)
    cols += [(b.key + "_low", f"{b.label.split()[0]} {b.band[0]:g} (est.)", b.band[0], b.paradigm, b.status),
             (b.key + "_high", f"{b.label.split()[0]} {b.band[1]:g} (est.)", b.band[1], b.paradigm, b.status)]
    return cols


# ------------------------------------------------- interconnect wire tables
# C59 (A6, O8): the h-tree PHYSICAL per-level wire lengths -- the ENERGY-side
# table, root-first, in slot units, for the shipped lambda-1 host topology
# (the macro level's 8-slot 2x4 grid at branching 4, depth 2). Registered as
# LITERALS by ruling: h_tree is the collaborator's lambda-1 host (S5), so the
# solver on their side must be able to read the same table -- the RULE that
# produced it ("each branching step halves the subtree's linear span; level l
# length = extent / 2**l, extent = the larger grid dimension in slots:
# 2x4 -> 4 -> [4/2, 4/4]") is implemented in interconnect.HTree and a test
# asserts rule == literals. The latency-side level_length convention is
# untouched (O8 ruled the latency side right). Replaceable by the real
# layout's measured lengths, like every wire model in this family.
HTREE_MACRO_LEVEL_LENGTH_SLOTS = (2.0, 1.0)


# ----------------------------------------------------------------- chip points
@dataclass(frozen=True)
class ChipPoint:
    """A real system as a point of the phase diagram: a device-speed
    coordinate and a bandwidth coordinate per level, EACH with its own
    status. Digital NoCs are not chip points: they have no honest compute
    coordinate in this model and are drawn as horizontal bandwidth lines
    (the anchors above).

    NORMALIZATION RULES (C37) -- every coordinate is in OUR geometry:
    * t_mvm_s is PER TOKEN: the time for one input row through the chip's
      resident array stack. A TOPS-derived row time is tile-shape
      INVARIANT (t = n_arrays x 2RC / TOPS), because the ops per row
      already scale with the array dimensions -- so no array-height
      folding (Mythic's 1024-row tile and ISAAC's 128-row array need no
      rescaling; folding them would double-count the height).
    * A bandwidth coordinate is what the chip's fabric supplies to the
      array group ONE OF OUR LINKS serves (a macro = 32 crossbars of
      256x256): a published PER-PHYSICAL-LINK rate (ondie_gbps_per_link)
      is aggregated -- links per array x 32 -- before it becomes the
      coordinate; comparing a single physical link against our per-macro
      knee is a granularity mismatch (the C36 figure did, corrected here).
      The estimated bands are AUTHORED at our granularity (a macro-trunk
      datapath estimate) and need no aggregation."""
    key: str
    label: str
    fabric: str                       # what the paper describes
    tier: str                         # hub-io | bus-T1 | star | mesh
    source: str
    # "analog" chips are the device marks of the r=1 machinery; a
    # "digital" chip point (C47: Simba, via its C41 equivalent-throughput
    # declaration) sits on the plane as a chip but is NOT a device mark.
    paradigm: str = "analog"
    t_mvm_s: Optional[float] = None
    t_mvm_status: str = "pending"     # measured | derived | design-point | pending
    t_mvm_derivation: str = ""
    ondie_gbps: Optional[float] = None               # THE COORDINATE, our geometry (C37)
    ondie_gbps_per_link: Optional[float] = None      # published per-physical-link rate, if any
    ondie_band: Optional[Tuple[float, float]] = None
    ondie_status: str = "not published"
    d2d_gbps: Optional[float] = None
    d2d_band: Optional[Tuple[float, float]] = None
    d2d_status: str = "n/a"


CHIPS = [
    ChipPoint("neurram", "NeuRRAM (2022)",
              "48 CIM cores, 256x256 RRAM each; inter-core buffers and partial-sum accumulation on the board FPGA; no on-chip core network",
              "hub-io", "Wan et al., Nature 2022; this model's calibrated macro (wan_nature_2022)",
              t_mvm_s=T_MVM_S, t_mvm_status="measured",
              t_mvm_derivation="7 encoded input bit slices x 1.4486 us (CiMLoop calibration of the macro)",
              ondie_status="not published (chip IO through the board FPGA, 130 nm; hub-IO bound)"),
    ChipPoint("hermes", "HERMES 64-core (2023)",
              "64 PCM cores, 256x256 each; 418 physical links in a 5 Parallel Prism fabric with per-core link controllers; compile-time scheduled",
              "star", "Le Gallo et al., Nat. Electron. 2023 (arXiv:2212.02872)",
              t_mvm_s=63.1e12 ** -1 * 64 * 2 * 256 * 256, t_mvm_status="derived",
              t_mvm_derivation="63.1 TOPS peak / 64 cores / (2 x 256 x 256 ops per MVM row) = ~133 ns per row",
              ondie_gbps=32 * (418.0 / 64) * 0.4,
              ondie_gbps_per_link=0.4,
              ondie_status="derived (C37 normalization): per PHYSICAL link 0.4 GB/s is published "
                           "(spec table: max link data-rate 3.2 Gbit/s; the analog band's low end); "
                           "the coordinate aggregates it to our per-macro-link granularity: "
                           "(418 links / 64 cores) x 0.4 GB/s x 32 arrays ~= 83.6 GB/s, assuming "
                           "the ~6.5 links per core run concurrently (Parallel Prism, 'at most six "
                           "neighboring cores')"),
    ChipPoint("isaac", "ISAAC (2016, design point)",
              "128x128 RRAM crossbars in tiles on a concentrated-mesh NoC (architecture study, not silicon)",
              "mesh", "Shafiee et al., ISCA 2016",
              t_mvm_s=16 * 100e-9, t_mvm_status="design-point",
              t_mvm_derivation="16 one-bit input slices x 100 ns per crossbar read",
              ondie_band=(0.4, 8.0), ondie_status="estimated (the paper sizes a 32 nm c-mesh, no per-link figure)"),
    ChipPoint("mx100", "TetraMem MX100",
              "10 NPUs + RISC-V + DMA engine + shared SRAM (512 KB + 1 MB), 65 nm; shared medium, no per-link bandwidth",
              "bus-T1", "TetraMem, arXiv:2410.14882",
              t_mvm_status="pending (BLOCKED on the source, checked 2026-09-01: the SoC paper "
                            "arXiv:2410.14882 publishes no TOPS or MVM rate and product material has "
                            "none citable; revisit on TetraMem's 22nm SoC publication -- C36)",
              ondie_band=(0.4, 8.0), ondie_status="estimated (SRAM port width x clock; a T1 number in this model)"),
    ChipPoint("simba", "Simba 36-chiplet (2019)", 
              "36 chiplets x 16 digital PEs (8x8-wide vector MACs, 32 KiB resident weights each); hierarchical 4x5 NoC + 6x6 GRS NoP, X-Y routed, hybrid wormhole/cut-through",
              "mesh", "Shao et al., MICRO'19 + Zimmer et al., JSSC 2020; the C41-C47 reproduction preset (analysis/SIMBA_PREREG.md)",
              paradigm="digital",
              t_mvm_s=2 * 32768 / (128 * 1.03e9), t_mvm_status="derived",
              t_mvm_derivation="C37 per-token rule on the C41 equivalent-throughput device: one input "
                               "row through a PE's resident 32 KiB = 2 x 32,768 ops / (128 ops/cycle "
                               "x 1.03 GHz, the experiment point) = 497 ns; shape-invariant "
                               "(576 PEs x 65,536 ops / 75.9 TOPS gives the same)",
              ondie_gbps=2 * 8.75 * 32, ondie_gbps_per_link=8.75,
              ondie_status="derived (C37 normalization): 70 Gb/s per NoC link at 0.72 V is published "
                           "(JSSC §II-C); a 256x256-array equivalent = 2 PEs (65,536 resident "
                           "weights) -> 2 links x 8.75 GB/s x 32 arrays = 560 GB/s per macro-group",
              d2d_gbps=12.5,
              d2d_status="measured (GRS 25 Gb/s max mode = the diagram's D2D line; the placement "
                         "experiments ran the 11 Gb/s mode = 5.5 GB/s, SIMBA_EXPERIMENT_GRS_GBPS)"),
    ChipPoint("mythic_m1076", "Mythic AMP M1076",
              "76 analog tiles, each with 64 KB SRAM + NoC router; compile-time scheduled",
              "star", "Mythic product material (no academic publication): 25 TOPS peak, 76 tiles, 80M weights on chip",
              t_mvm_s=25e12 ** -1 * 76 * 2 * 1024 * 1024, t_mvm_status="derived",
              t_mvm_derivation="25 TOPS peak / 76 tiles / (2 x 1024 x 1024 ops per MVM row) = ~6.4 us per row; "
                               "the 1024x1024 tile array from 80M weights / 76 tiles = 1.05M (C36)",
              ondie_band=(0.4, 8.0), ondie_status="estimated (router width / clock not published)"),
    ChipPoint("tsinghua_multichip", "Tsinghua multi-chip (2025)",
              "8 RRAM chips (144k cells each) + FPGA hub; no chip-to-chip direct links, everything through the FPGA",
              "hub-io", "Nat. Commun. 2025 (predecessor: Yao et al., Nature 2020, 8 PEs + FPGA)",
              t_mvm_status="pending", d2d_band=(0.1, 2.0),
              d2d_status="estimated (board-level links through the FPGA hub)"),
]


def chip(key: str) -> ChipPoint:
    for c in CHIPS:
        if c.key == key:
            return c
    raise KeyError(key)


def hermes_self_consistency():
    """V0 (C37): HERMES audited against its own knee, from published numbers
    only. Need per core per token: 256 INT8 inputs every t_MVM; supply per
    core: (418 links / 64 cores) x 0.4 GB/s. Supply exceeds need by ~1.36x:
    a fabricated analog chip provisioned its fabric just ABOVE its own
    knee -- the first external silicon point validating the knee formula
    (boundary = traffic / compute time), and consistent with its measured
    63.1 TOPS (a fabric 38x under the knee, as the C36 mis-reading implied,
    could not have sustained it)."""
    c = chip("hermes")
    need = 256.0 / c.t_mvm_s / 1e9                 # GB/s per core, one row per t_MVM
    supply = (418.0 / 64) * c.ondie_gbps_per_link  # GB/s per core, aggregate ingress
    return {"need_gbps_per_core": need, "supply_gbps_per_core": supply,
            "headroom": supply / need}


def device_marks():
    """The silicon marks of the device axis (O17b): every ANALOG chip point
    with a t_MVM coordinate, value AND status straight from the registry --
    the only source a plane figure may draw device marks from. Everything
    between the marks is a closed-form surface, not a measurement: NeuRRAM
    is measured, ISAAC a design point, HERMES derived from peak TOPS.
    Digital chip points (C47: Simba) are excluded by paradigm -- they sit
    on the plane as chips, not as device marks of the r=1 machinery."""
    return sorted((c for c in CHIPS if c.t_mvm_s is not None
                   and c.paradigm == "analog"),
                  key=lambda c: -c.t_mvm_s)


# ----------------------------------------------------------------- summaries
def grid_rows():
    """The paradigm x level grid as table rows (for ANCHORS.md and the CLI)."""
    rows = []
    for a in ANCHORS:
        val = f"{a.gbps:g} GB/s" if a.gbps is not None else f"{a.band[0]:g}-{a.band[1]:g} GB/s (band)"
        wc = ", ".join(f"{w:,.0f}" for w in a.words_per_cycle())
        rows.append((a.level, a.paradigm, a.label, val, wc, a.status, a.source))
    return rows


def as_json():
    return {"cycle_s": CYCLE_S, "t_mvm_s": T_MVM_S, "slices_per_mvm": SLICES_PER_MVM,
            "device": DEVICE.name,
            "wc_per_gbps": WC_PER_GBPS,
            "anchors": [asdict(a) for a in ANCHORS],
            "chips": [asdict(c) for c in CHIPS]}


if __name__ == "__main__":
    print(f"device {DEVICE.name}: cycle {CYCLE_S*1e6:.4f} us per slice, {T_MVM_S*1e6:.2f} us per MVM row; "
          f"1 GB/s = {WC_PER_GBPS:,.1f} words/cycle\n")
    print(f"{'level':6} {'paradigm':18} {'anchor':22} {'value':22} {'words/cycle':16} {'status':12}")
    for lv, pa, lab, val, wc, st, _ in grid_rows():
        print(f"{lv:6} {pa:18} {lab:22} {val:22} {wc:16} {st:12}")
    print("\nchip points (phase diagram):")
    for c in CHIPS:
        t = f"{c.t_mvm_s*1e6:.3f} us ({c.t_mvm_status})" if c.t_mvm_s else f"-- ({c.t_mvm_status})"
        od = (f"{c.ondie_gbps:g} GB/s" if c.ondie_gbps else
              f"{c.ondie_band[0]:g}-{c.ondie_band[1]:g} GB/s" if c.ondie_band else "--")
        print(f"  {c.label:28} tier {c.tier:7} t_MVM {t:28} on-die {od:14} [{c.ondie_status}]")
