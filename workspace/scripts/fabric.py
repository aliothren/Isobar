"""Physical fabric: the schema and loader for models/fabric/*.yaml.

The YAML holds the concrete chip data (levels, counts, grids, link params);
this module holds the abstraction: dataclasses, validation, the cross-check
against a run's stats, and grid-slot coordinates. Pure python -- imports on
host and container alike (yaml is loaded lazily inside from_yaml).

Authority direction: the fabric config is the source of truth for physical
structure; the stats-derived counts (crossbar_stats.hierarchy) are demoted to a
consistency check via verify_against_stats().
"""
import os
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

_DEFAULT_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "models", "fabric", "mlx300.yaml")


@dataclass(frozen=True)
class Device:
    """The analog device the die is built from (O17a / C30): the two numbers
    that turn every words-per-cycle reading of this model into seconds -- the
    cycle per input bit slice and the slices per MVM row (t_MVM = cycle x
    slices). PLATFORM INPUT, declared in the fabric YAML; every latency and
    every GB/s <-> words/cycle conversion reads it (the anchor registry
    included), and a run's CiMLoop cycle (GLOBAL_CYCLE_SECONDS of the macro)
    is checked against it (Fabric.verify_cycle). The shipped value is the
    calibrated wan_nature_2022 macro: 10.14 us per MVM row over 7 slices.

    device_class (C41): which self-check regime the device belongs to.
    "reram_macro" (default) = a CiMLoop-calibrated analog macro backs the
    declaration, and verify_cycle reconciles against it on every run.
    "digital_throughput" = an abstract equivalent-throughput unit (the Simba
    reproduction preset): the declared cycle IS the truth, there is no macro
    to reconcile, and verify_cycle is a no-op -- but validate()'s sanity
    checks still apply. The bypass is keyed on THIS explicit field only,
    never inferred from missing ReRAM parameters (a typo'd ReRAM config must
    still fail loudly)."""
    name: str = "wan_nature_2022 (NeuRRAM class, 130 nm RRAM)"
    cycle_seconds: float = 10.14e-6 / 7        # per input bit slice
    input_slices_per_mvm: int = 7              # signed 8-bit inputs, encoded
    calibration: str = "CiMLoop calibration of the macro (Wan et al., Nature 2022)"
    device_class: str = "reram_macro"

    @property
    def t_mvm_s(self) -> float:
        """Seconds per MVM row through one crossbar: the device-speed axis."""
        return self.cycle_seconds * self.input_slices_per_mvm

    def words_per_cycle(self, gbps: float) -> float:
        """GB/s -> words per device cycle (1 word = 8 bits)."""
        return gbps * 1e9 * self.cycle_seconds

    def gbps(self, wc: float) -> float:
        return wc / (1e9 * self.cycle_seconds)


# The explicit whitelist behind Device.device_class (C41): a typo must fail
# in validate(), never silently select a regime.
DEVICE_CLASSES = ("reram_macro", "digital_throughput")


@dataclass(frozen=True)
class Link:
    """The network connecting a level's instances to their parent's hub.

    Propagation may be declared either as `ns_per_hop` directly or as
    `ns_per_mm` (C38, hygiene: slot_pitch_um's first consumer) -- then
    ns_per_hop = ns_per_mm x the level's slot_pitch_um / 1000 at load;
    both at once is an error. The shipped configs keep their explicit
    per-hop values (DR-4 placeholders), so nothing published moves."""
    name: str
    ns_per_hop: float
    ns_per_mm: Optional[float] = None        # if set, ns_per_hop was derived from it
    pj_per_word: Optional[float] = None      # None = priced elsewhere / not priced
    cimloop_component: Optional[str] = None  # calibrated component (re-priced by distance)
    reference_hops: Optional[float] = None
    calibration: Optional[str] = None        # DR tag for the placeholder
    # T2 static-contention input (link_occupancy); None = unlimited (no stall).
    # Owned by OUR analytic tier, never pushed into Timeloop (ownership rule:
    # network links -> T2, storage/hub bandwidth -> T1 via Level.hub_bandwidth).
    bandwidth_words_per_cycle: Optional[float] = None
    # Packet model (C46 / SIMBA_PREREG A3), NoC-paradigm links only:
    # packet_payload_bytes = data bytes per packet (None = no packet model;
    # every shipped production config); packet_wire_overhead = header
    # share on the wire (>= 1), an unconditional serialization multiplier.
    # The per-packet hop term these enable is the PESSIMISTIC end of the
    # packet bracket -- the optimistic end keeps busiest-wire semantics.
    packet_payload_bytes: Optional[float] = None
    packet_wire_overhead: float = 1.0
    # Which communication SCHEME connects this level's instances to their hub.
    # "star" (private link per node) is the degenerate default and reproduces the
    # pre-W2 behaviour exactly. Every scheme takes its OWN parameter set, so they
    # live in `params` rather than as flat fields; scripts/interconnect.py owns
    # the registry and validates them.
    topology: str = "star"
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Level:
    name: str
    per_parent: int = 1
    mesh: Optional[Tuple[int, int]] = None   # (X, Y) grid inside the parent
    link: Optional[Link] = None
    # T1: this level's HUB storage read/write bandwidth (words/cycle), pushed
    # into the Timeloop spec (e.g. the die's glb). None = unlimited.
    # VALUE units (O28/C34): consumed by the analytic T1 axis
    # (sweep_axes.axis_t1_hub). mlx_system pushes it into Timeloop's glb
    # attributes, where Timeloop counts in ITS units (x7 / x8) -- that path
    # is validation-only; leave unset in shipped configs.
    hub_bandwidth_words_per_cycle: Optional[float] = None
    # O27 (C57): per-INSTANCE idle (static) power of this level's component,
    # in watts. PLATFORM INPUT, default None = static power not modeled
    # (the shipped state; the dynamic-only account stays exactly as
    # published). The closed-form static term is
    #   E_static = sum over levels of idle_power_w x instance count x makespan,
    # so it INHERITS the latency ordering structurally. Values enter only
    # from DR inputs or literature anchors under the anchor provenance
    # discipline -- never estimated in place.
    idle_power_w: Optional[float] = None
    # Physical centre-to-centre distance between adjacent slots of THIS level's
    # grid, in micrometres. Platform input (example default in the shipped
    # configs); nothing consumes it yet -- it exists so hop counts have a
    # declared physical meaning, and so ns_per_hop / hop_scale can later be
    # DERIVED (delay ~ length or length^2, energy ~ wire capacitance ~ length)
    # instead of hand-filled per level. None = not stated.
    slot_pitch_um: Optional[float] = None
    # The level's PORT RATIO kappa = C_port / C_link: each instance's one
    # injection and one ejection port run at kappa x the level's link rate
    # (S8). Declared in the YAML as `ports: {ratio: kappa}` on the level;
    # None = not declared. The deployment evaluator reads the ratio from
    # the workload object (W.port_ratio); the command line
    # (scripts/cimsim_cli.py) takes this field as its default when no
    # --kappa is given, so a fabric file can carry its own port model.
    port_ratio: Optional[float] = None


@dataclass(frozen=True)
class DigitalUnit:
    """The die's digital vector unit (O24): where the non-matmul operators
    (softmax, GELU, LayerNorm, residual adds) run, next to the glb. Every
    field is a PLATFORM INPUT (DR-8); the shipped values are a generic
    configuration: lanes x clock sized to the die's array output rate
    (256 arrays x 128 outputs per device cycle, 1.4486 us = 22.6 G results/s -> 32-64 lanes
    at 1 GHz keep pace), per-op energies from the Horowitz ISSCC 2014 45 nm
    table at the 16-bit intermediate width (see ANCHORS.md)."""
    lanes: int = 64                     # elements processed per digital cycle
    clock_hz: float = 1.0e9             # the digital clock (NOT the array cycle)
    pj_add: float = 0.05                # 16-bit integer add
    pj_mul: float = 0.6                 # 16-bit multiply (example; 8-bit is 0.2)
    pj_lut: float = 1.0                 # one table lookup (exp / tanh / rsqrt)
    intermediate_bits: int = 16         # softmax / LayerNorm intermediates
    calibration: str = "DR-8: generic example values (ANCHORS.md)"

    def ops_per_second(self) -> float:
        return self.lanes * self.clock_hz


@dataclass(frozen=True)
class AttentionUnit:
    """The external unit that receives the attention under offload (O9): an
    ABSTRACT NPU-class digital engine off the die, at the package attach
    point, with its own K/V memory. No internal structure is modeled; the
    interface is this parameter set (platform input DR-9). Shipped values are
    generic public figures (ANCHORS.md): an edge-NPU-class engine (4 TOPS
    INT8 at 2 W -> 2 T MAC/s, 1 pJ per MAC all-in), LPDDR4-class K/V memory
    (25.6 GB/s, ~6 pJ/bit -> 50 pJ per 8-bit word), and a die<->unit link of
    the same class as the die-to-die links (Simba GRS: 12.5 GB/s per
    direction, 10 pJ per word)."""
    mac_per_second: float = 2.0e12          # internal compute rate
    pj_per_mac: float = 1.0                 # internal average cost per MAC (all-in)
    call_overhead_s: float = 0.0            # fixed per-layer invocation overhead
    kv_words_per_second: float = 25.6e9     # K/V memory bandwidth (8-bit words)
    kv_pj_per_word_read: float = 50.0
    kv_pj_per_word_write: float = 50.0
    kv_capacity_words: float = 2.0e9        # 2 GB
    # 12.5 GB/s (Simba GRS) at the default device cycle; the YAML declares
    # `link_bandwidth_gbps` and the loader converts at the fabric's device
    link_bandwidth_words_per_cycle: float = 12.5e9 * (10.14e-6 / 7)
    link_pj_per_word: float = 10.0
    link_reference_hops: float = 1.0
    n_units: int = 1                        # units sharing the model's layers
    calibration: str = "DR-9: generic public figures (ANCHORS.md)"


@dataclass(frozen=True)
class Fabric:
    name: str
    levels: List[Level] = field(default_factory=list)
    cimloop: dict = field(default_factory=dict)
    # the digital vector unit (O24); None = the platform default configuration
    digital: DigitalUnit = field(default_factory=DigitalUnit)
    # the analog device (O17a): cycle per input slice x slices per MVM row.
    # Bandwidths declared in GB/s in the YAML are converted with THIS cycle.
    device: Device = field(default_factory=Device)
    # off-chip port bandwidth for the model's embedding read (words/cycle at
    # the device cycle); None = not set -> the read is priced but not timed
    offchip_bandwidth_words_per_cycle: Optional[float] = None
    # the external attention unit (O9); the platform default configuration
    attention_unit: AttentionUnit = field(default_factory=AttentionUnit)
    # Width of a PARTIAL SUM crossing a link, in units of the 8-bit activation
    # word (O23). Outputs travelling UP the tree are partial sums until the
    # reduction completes at the top: W4 x A8 accumulated over K rows is
    # 12 + log2(K) bits, and cross-unit digital accumulation is commonly kept
    # at 16 bits -> 2 words per element by default. Platform input (DR-7):
    # the real chip's ADC / accumulator width decides.
    psum_word_bytes: float = 2.0
    # Schedule slack (O26 / C29, platform input): the busiest-wire occupancy is
    # the least time ANY schedule can spend on that wire for the given routing
    # -- exact for private links and a shared bus, optimistic for a routed
    # grid. A schedule that cannot reach the bound is a factor >= 1 on every
    # occupancy; 1.0 = the bound. `link_occupancy` applies it.
    schedule_slack: float = 1.0

    # ------------------------------------------------------------- access
    def level(self, name: str) -> Level:
        for lv in self.levels:
            if lv.name == name:
                return lv
        raise KeyError(f"fabric {self.name} has no level '{name}'")

    def count_below(self, name: str) -> int:
        """Cumulative instances of `name` inside one top-level instance."""
        n = 1
        for lv in self.levels:
            n *= lv.per_parent
            if lv.name == name:
                return n
        raise KeyError(f"fabric {self.name} has no level '{name}'")

    def pitch(self, name: str) -> int:
        """Leaf-grid units spanned by ONE slot step at `name`'s level.

        The product of every mesh BELOW it. This is the bridge between the two
        coordinate systems the cost paths use: an interconnect works in a level's
        own slot units, the propagation-latency term wants global leaf-grid units,
        and leaf_distance == slot_distance * pitch exactly (the nesting is an
        affine map, so Manhattan distance scales). Verified against the legacy
        constants: macro pitch 6 (2.0 slots -> 12), core 3 (1.0 -> 3),
        crossbar 1 (2.0 -> 2).
        """
        seen = False
        p = 1
        for lv in self.levels:
            if seen and lv.mesh is not None:
                p *= lv.mesh[0]
            if lv.name == name:
                seen = True
        if not seen:
            raise KeyError(f"fabric {self.name} has no level '{name}'")
        return p

    def grid_shape(self) -> Tuple[int, int]:
        """Full leaf-grid dimensions: per-axis product of every mesh."""
        gx = gy = 1
        for lv in self.levels:
            if lv.mesh is not None:
                gx *= lv.mesh[0]
                gy *= lv.mesh[1]
        return gx, gy

    def slots(self, name: str) -> List[Tuple[int, int]]:
        """Grid coordinates a level's instances occupy in their parent,
        row-major fill order (matches the legacy nested floorplan)."""
        lv = self.level(name)
        if lv.mesh is None:
            raise ValueError(f"level '{name}' has no mesh")
        mx, _ = lv.mesh
        return [(i % mx, i // mx) for i in range(lv.per_parent)]

    # ------------------------------------------------------------- checks
    def verify_cycle(self, cycle_seconds: float, rtol: float = 1e-9) -> None:
        """The run's CiMLoop cycle (the macro's GLOBAL_CYCLE_SECONDS) must be
        the fabric's device cycle: the fabric declares, CiMLoop is the
        calibrated source it is checked against (O17a). Raises on mismatch.

        C41: for device_class "digital_throughput" there is no macro to
        reconcile -- the declared cycle is the truth and this check is a
        no-op. The bypass reads the EXPLICIT class field only."""
        if self.device.device_class == "digital_throughput":
            return
        d = self.device.cycle_seconds
        if abs(cycle_seconds - d) > rtol * d:
            raise ValueError(
                f"fabric {self.name} declares device.cycle_seconds = {d:.7g} s but the run's "
                f"CiMLoop macro cycle is {cycle_seconds:.7g} s -- fabric device and CiMLoop macro diverged")

    def validate(self) -> "Fabric":
        if self.device.device_class not in DEVICE_CLASSES:
            raise ValueError(
                f"device_class must be one of {DEVICE_CLASSES}, got "
                f"'{self.device.device_class}' -- the verify_cycle regime is "
                f"selected by this explicit field only (C41)")
        if not (self.device.cycle_seconds > 0):
            raise ValueError(f"device.cycle_seconds must be > 0, got {self.device.cycle_seconds}")
        if self.device.input_slices_per_mvm < 1:
            raise ValueError(f"device.input_slices_per_mvm must be >= 1, got {self.device.input_slices_per_mvm}")
        for lv in self.levels:
            lk = lv.link
            if lk is not None:
                if lk.packet_payload_bytes is not None and lk.packet_payload_bytes <= 0:
                    raise ValueError(f"{lv.name}: packet_payload_bytes must be > 0")
                if lk.packet_wire_overhead < 1.0:
                    raise ValueError(f"{lv.name}: packet_wire_overhead must be >= 1")
                # C60 (A7, review clause 1): a folded scheme splits router
                # COUNT from physical LENGTH (hops() returns the folded
                # length), so per-router packet constants must not silently
                # read hops -- refuse the combination until the packet path
                # consumes router_hops() explicitly.
                if (lk.packet_payload_bytes is not None
                        and lk.topology in ("torus", "ring", "express",
                                            "cmesh", "hier_wide")):
                    raise ValueError(
                        f"{lv.name}: packet parameters on count-length-split scheme "
                        f"'{lk.topology}' -- hops() returns folded PHYSICAL "
                        f"length there, not the router count; wire the packet "
                        f"path to router_hops() before enabling this")
        if not (self.schedule_slack >= 1.0):
            raise ValueError(f"schedule_slack must be >= 1.0 (1.0 = the busiest-wire bound), got {self.schedule_slack}")
        for lv in self.levels:
            if lv.per_parent < 1:
                raise ValueError(f"{lv.name}: per_parent must be >= 1")
            if lv.mesh is not None and lv.mesh[0] * lv.mesh[1] < lv.per_parent:
                raise ValueError(
                    f"{lv.name}: mesh {lv.mesh} has fewer slots than "
                    f"per_parent {lv.per_parent}")
        for lv in self.levels:
            if lv.idle_power_w is not None and lv.idle_power_w < 0:
                raise ValueError(f"{lv.name}: idle_power_w must be >= 0")
            if lv.port_ratio is not None and lv.port_ratio < 1.0:
                raise ValueError(f"{lv.name}: ports.ratio must be >= 1 (1 = ports at the link rate), got {lv.port_ratio}")
        # physical slot pitch: positive, and non-decreasing toward the top
        # (a parent level's grid step spans at least its child's)
        pitched = [lv for lv in self.levels if lv.slot_pitch_um is not None]
        for lv in pitched:
            if lv.slot_pitch_um <= 0:
                raise ValueError(f"{lv.name}: slot_pitch_um must be > 0")
        for upper, lower in zip(pitched, pitched[1:]):   # top -> bottom
            if upper.slot_pitch_um < lower.slot_pitch_um:
                raise ValueError(
                    f"slot_pitch_um not monotone up the tree: {upper.name} "
                    f"({upper.slot_pitch_um}) < {lower.name} "
                    f"({lower.slot_pitch_um})")
        # unit costs must be non-decreasing toward the top of the tree
        links = [lv.link for lv in self.levels if lv.link is not None]
        for upper, lower in zip(links, links[1:]):      # levels are top -> bottom
            if upper.ns_per_hop < lower.ns_per_hop:
                raise ValueError(
                    f"ns_per_hop not monotone up the tree: {upper.name} "
                    f"({upper.ns_per_hop}) < {lower.name} ({lower.ns_per_hop})")
            if (upper.pj_per_word is not None and lower.pj_per_word is not None
                    and upper.pj_per_word < lower.pj_per_word):
                raise ValueError(
                    f"pj_per_word not monotone up the tree: {upper.name} "
                    f"({upper.pj_per_word}) < {lower.name} ({lower.pj_per_word})")
        # each level's scheme validates its own parameter set
        from scripts import interconnect
        for lv in self.levels:
            if lv.link is not None:
                interconnect.validate_params(lv.link.topology, lv.link.params,
                                             where=lv.name)
        return self

    def verify_against_stats(self, hier: dict) -> None:
        """Cross-check against crossbar_stats.hierarchy() output (cumulative
        instance counts parsed from a run). Raises on mismatch: the config is
        the authority, a run that disagrees with it is misconfigured.

        Counts are PER DIE: a CiMLoop run always models one die, so a
        multi-die fabric (die.per_parent > 1) must not inflate the expectation.
        """
        dies = self.count_below("die")
        expected = {"n_macros": self.count_below("macro") // dies,
                    "n_cores": self.count_below("core") // dies,
                    "n_crossbars": self.count_below("crossbar") // dies}
        for key, exp in expected.items():
            got = hier.get(key)
            if got != exp:
                raise ValueError(
                    f"fabric {self.name} says {key}={exp} but the run's stats "
                    f"say {got} -- CiMLoop spec and fabric config diverged")


def from_yaml(path: str = _DEFAULT_YAML) -> Fabric:
    import yaml
    with open(path) as f:
        raw = yaml.safe_load(f)["fabric"]
    dv = raw.get("device") or {}
    device = Device(name=str(dv.get("name", Device.name)),
                    cycle_seconds=float(dv.get("cycle_seconds", Device.cycle_seconds)),
                    input_slices_per_mvm=int(dv.get("input_slices_per_mvm", Device.input_slices_per_mvm)),
                    calibration=str(dv.get("calibration", Device.calibration)),
                    device_class=str(dv.get("device_class", Device.device_class)))

    def bw(obj, key_wc, key_gbps, where):
        """A bandwidth declared EITHER in GB/s (converted at the device cycle)
        or in words per cycle; both at once is an error; neither = None."""
        a, b = obj.get(key_wc), obj.get(key_gbps)
        if a is not None and b is not None:
            raise ValueError(f"{path}: {where}: declare {key_gbps} or {key_wc}, not both")
        if b is not None:
            return device.words_per_cycle(float(b))
        return None if a is None else float(a)
    def hop_ns(link, lv):
        """ns_per_hop declared directly OR derived from ns_per_mm x the
        level's slot_pitch_um (C38); both at once is an error."""
        nh, nm = link.get("ns_per_hop"), link.get("ns_per_mm")
        if nh is not None and nm is not None:
            raise ValueError(f"{path}: {lv['name']}.link: declare ns_per_hop or ns_per_mm, not both")
        if nm is not None:
            pitch = lv.get("slot_pitch_um")
            if pitch is None:
                raise ValueError(f"{path}: {lv['name']}.link: ns_per_mm needs the level's slot_pitch_um")
            return float(nm) * float(pitch) / 1000.0
        if nh is None:
            raise ValueError(f"{path}: {lv['name']}.link: declare ns_per_hop or ns_per_mm")
        return float(nh)

    levels = []
    for lv in raw["levels"]:
        link = lv.get("link")
        levels.append(Level(
            name=lv["name"],
            per_parent=int(lv.get("per_parent", 1)),
            mesh=tuple(lv["mesh"]) if lv.get("mesh") else None,
            link=Link(name=link["name"],
                      ns_per_hop=hop_ns(link, lv),
                      ns_per_mm=(None if link.get("ns_per_mm") is None
                                 else float(link["ns_per_mm"])),
                      pj_per_word=(None if link.get("pj_per_word") is None
                                   else float(link["pj_per_word"])),
                      cimloop_component=link.get("cimloop_component"),
                      reference_hops=(None if link.get("reference_hops") is None
                                      else float(link["reference_hops"])),
                      calibration=link.get("calibration"),
                      bandwidth_words_per_cycle=bw(link, "bandwidth_words_per_cycle",
                                                   "bandwidth_gbps", lv["name"] + ".link"),
                      packet_payload_bytes=(None if link.get("packet_payload_bytes") is None
                                            else float(link["packet_payload_bytes"])),
                      packet_wire_overhead=float(link.get("packet_wire_overhead", 1.0)),
                      topology=link.get("topology", "star"),
                      params=dict(link.get("params") or {})) if link else None,
            hub_bandwidth_words_per_cycle=bw(lv, "hub_bandwidth_words_per_cycle",
                                             "hub_bandwidth_gbps", lv["name"]),
            idle_power_w=(None if lv.get("idle_power_w") is None
                          else float(lv["idle_power_w"])),
            slot_pitch_um=(None if lv.get("slot_pitch_um") is None
                           else float(lv.get("slot_pitch_um"))),
            port_ratio=(None if (lv.get("ports") or {}).get("ratio") is None
                        else float(lv["ports"]["ratio"])),
        ))
    dg = raw.get("digital") or {}
    digital = DigitalUnit(
        lanes=int(dg.get("lanes", DigitalUnit.lanes)),
        clock_hz=float(dg.get("clock_hz", DigitalUnit.clock_hz)),
        pj_add=float(dg.get("pj_add", DigitalUnit.pj_add)),
        pj_mul=float(dg.get("pj_mul", DigitalUnit.pj_mul)),
        pj_lut=float(dg.get("pj_lut", DigitalUnit.pj_lut)),
        intermediate_bits=int(dg.get("intermediate_bits", DigitalUnit.intermediate_bits)),
        calibration=str(dg.get("calibration", DigitalUnit.calibration)))
    ob = bw(raw, "offchip_bandwidth_words_per_cycle", "offchip_bandwidth_gbps", "fabric")
    au = dict(raw.get("attention_unit") or {})
    ulink = bw(au, "link_bandwidth_words_per_cycle", "link_bandwidth_gbps", "attention_unit")
    au.pop("link_bandwidth_gbps", None); au.pop("link_bandwidth_words_per_cycle", None)
    unit = AttentionUnit(**{k: (int(v) if k == "n_units" else (str(v) if k == "calibration" else float(v)))
                            for k, v in au.items()},
                         **({} if ulink is None else {"link_bandwidth_words_per_cycle": ulink}))
    return Fabric(name=raw["name"], levels=levels,
                  cimloop=raw.get("cimloop", {}),
                  psum_word_bytes=float(raw.get("psum_word_bytes", 2.0)),
                  schedule_slack=float(raw.get("schedule_slack", 1.0)),
                  digital=digital, device=device,
                  offchip_bandwidth_words_per_cycle=ob,
                  attention_unit=unit,
                  ).validate()


_CACHE = {}


def provenance(fab: "Fabric") -> dict:
    """What the fabric IS, for every result JSON (C27: a whole chain of
    results once carried no record of the macro grid they were computed on)."""
    def mesh(name):
        lv = next((l for l in fab.levels if l.name == name), None)
        return list(lv.mesh) if (lv is not None and lv.mesh) else None
    macro = next((l for l in fab.levels if l.name == "macro"), None)
    return {"name": fab.name, "die_mesh": mesh("die"), "macro_mesh": mesh("macro"),
            "core_mesh": mesh("core"), "crossbar_mesh": mesh("crossbar"),
            "macro_scheme": macro.link.topology if (macro and macro.link) else None,
            "schedule_slack": getattr(fab, "schedule_slack", 1.0),
            "device": {"name": fab.device.name, "cycle_seconds": fab.device.cycle_seconds,
                       "input_slices_per_mvm": fab.device.input_slices_per_mvm,
                       "t_mvm_s": fab.device.t_mvm_s,
                       "device_class": fab.device.device_class}}


def default() -> Fabric:
    """The active fabric config, loaded once per path.

    Defaults to models/fabric/mlx300.yaml; the CIMSIM_FABRIC environment
    variable selects another config file for a whole process tree -- the lever
    for running the same experiments on a fabric variant, e.g.
        CIMSIM_FABRIC=/home/workspace/models/fabric/mlx300_3x3.yaml python3 ...
    """
    path = os.path.abspath(os.environ.get("CIMSIM_FABRIC", _DEFAULT_YAML))
    if path not in _CACHE:
        _CACHE[path] = from_yaml(path)
    return _CACHE[path]