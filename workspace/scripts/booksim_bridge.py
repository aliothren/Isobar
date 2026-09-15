"""The BookSim bridge (C51, worklist step 4, day 1): calibers, batch
injection, and the two identity gates.

BookSim2 is event-level (per-flit routers, queueing, flow control); our
account is rate-level (busiest-wire division). The bridge maps ONE flow
set onto both so the cycle-accurate completion time can be placed inside
our bracket [optimistic rail, round-serialized rail]. Everything here is
governed by the step-4 pre-registration in FIXLIST (conversion table,
lambda guard, unicast-decomposition caliber label, expectations).

CONVERSION TABLE (each entry with provenance; the pre-registration is
the authority):
  flit payload      8 B   (64 data bits per flit; the 2 id bits are wire
                           format -- JSSC'20 SII-C; consistent with the
                           128 B = 16-payload-flit packet of the A3
                           bracket)
  channel cycle     1.454545 ns = 8 B / 5.5 GB/s  (the experiment-mode
                           link rate, MICRO'19 S4.1; BookSim moves one
                           flit per channel per cycle)
  hop latency       14 cycles TOTAL = channel 10 + router pipeline 4
                           (20 ns/hop, MICRO'19 Tab 2. Split AMENDED from
                           the ruling's 12+2: BookSim's default IQ router
                           pipeline measures 4 cycles/hop and overriding
                           its alloc delays trips a switch-timing
                           assertion -- so the stable alignment is
                           channel 10 + default router 4, same 14-cycle
                           total, same -1.8% optimistic remainder.
                           Silicon's own router is 2 of the 20 ns (JSSC
                           SII-C); the split here is tool alignment, the
                           TOTAL carries the provenance)
  packet            17 flits (1 head + 16 payload = 128 B payload)
  vc_buf_size       34 flits -- ALIGNED, not default (day-1 gate
                           finding): the default 8 cannot cover the
                           14-cycle hop's bandwidth-delay product and
                           credit-throttles every channel ~2x; silicon
                           sustains the full 70 Gb/s line rate (JSSC
                           SII-C), so the reference must cover BDP too.
                           Insensitive 34 vs 64 (gate A: 1.0018 both).
  INJECTION CALIBER (declared): BookSim gives each node ONE injection
  channel; Simba's NoP router has FOUR NoC-side local ports. Source-
  concentrated flow sets therefore bind on the injection channel in the
  bridge's caliber; every reference and BOTH rails use
  ref = max(mesh-channel bound, injection bound) consistently.
  interface base    7 cycles per packet -- BRIDGE-INTERNAL measured
                           constant (BookSim itself, BDP-aligned config;
                           lone 1-hop packet = 17 + 14 + 7; the default
                           8-flit buffer read 37). NO silicon
                           counterpart claimed (ruling: provenance level
                           labelled).
  UN-ALIGNED (BookSim defaults, declared; congestion-side only):
    num_vcs = 16, credit_delay = 2
"""
import math
import os
import re
import subprocess
import tempfile

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BOOKSIM = os.path.join(WS, "tools", "booksim2", "src", "booksim")
CONTAINER = "cimloop-tutorial-1"
# Dual invocation: inside the container (tests) the binary runs directly;
# from the host it goes through docker exec.
IN_CONTAINER = os.path.exists("/.dockerenv")

FLIT_PAYLOAD_B = 8.0
CHANNEL_CYCLE_S = FLIT_PAYLOAD_B / 5.5e9          # 1.4545 ns
PACKET_FLITS = 17
PACKET_PAYLOAD_B = 128.0
HOP_CHANNEL_CYCLES = 10
HOP_ROUTER_CYCLES = 4      # BookSim default IQ pipeline (measured; see table)
DEFAULTS_NOTE = {"num_vcs": 16, "vc_buf_size": 8, "credit_delay": 2}
LAMBDA_GUARD_FRAC = 0.10                           # the ruling's 10%


def available():
    return os.path.exists(BOOKSIM)


def packets_for(volume_bytes):
    return int(math.ceil(volume_bytes / PACKET_PAYLOAD_B))


MESH_K = 6                 # the bridge's default grid (the Simba NoP)


def _write_config(path, flow_path, extra=None, k=MESH_K):
    lines = [
        "topology = mesh;", f"k = {k};", "n = 2;",
        "routing_function = dor;",
        f"traffic = file({flow_path});",
        "sim_type = batch;",
        "batch_size = 1;",             # overridden per source by the patch
        f"packet_size = {PACKET_FLITS};",
        "injection_process = bernoulli;",
        "injection_rate = 1.0;",
        # hop latency: 12 channel cycles per link + the 2-cycle router
        # hop = 12 wire cycles on the channel (patched knob) + the
        # 2-cycle router realised as vc_alloc 1 + sw_alloc 1 (JSSC SII-C)
        # hop = 10 wire cycles on the channel (patched knob) + the
        # DEFAULT 4-cycle IQ router pipeline (overriding alloc delays
        # trips iq_router's switch-timing assertion; calibrated:
        # +16/hop at channel 12, +14/hop at channel 10)
        f"mesh_channel_latency = {HOP_CHANNEL_CYCLES};",
        "vc_buf_size = 34;",           # BDP-aligned (see table)
    ]
    if extra:
        lines += [f"{k} = {v};" for k, v in extra.items()]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


_DURATION = re.compile(r"Overall min batch duration = (\d+)")


def run_batch(flows, extra=None, latency_channel_cycles=HOP_CHANNEL_CYCLES,
              k=MESH_K):
    """flows: [(src_node, dst_node, n_packets)] on a k x k mesh (node =
    y*k+x, matching the repo's row-major die table; k defaults to the
    Simba NoP's 6). Returns completion cycles (inject + drain) and
    seconds at the NoP channel cycle."""
    if not available():
        raise FileNotFoundError(
            f"{BOOKSIM} missing -- build per tools/booksim2/BUILD_NOTES.md")
    tag = next(tempfile._get_candidate_names())
    flow_path = f"/tmp/bsflows_{tag}"
    cfg_path = f"/tmp/bscfg_{tag}"
    with open(f"/tmp/h_{tag}", "w") as f:      # host-side scratch, copied in
        pass
    hostflow = f"/tmp/hostflows_{tag}"
    with open(hostflow, "w") as f:
        for s, d, n in flows:
            f.write(f"{s} {d} {n}\n")
    hostcfg = f"/tmp/hostcfg_{tag}"
    ex = dict(extra or {})
    if latency_channel_cycles != HOP_CHANNEL_CYCLES:
        ex.setdefault("mesh_channel_latency", latency_channel_cycles)
    if IN_CONTAINER:
        os.replace(hostflow, flow_path)
        _write_config(cfg_path, flow_path, ex, k)
        out = subprocess.run([BOOKSIM, cfg_path],
                             capture_output=True, text=True)
    else:
        _write_config(hostcfg, flow_path, ex, k)
        subprocess.run(["docker", "cp", hostflow, f"{CONTAINER}:{flow_path}"],
                       check=True, capture_output=True)
        subprocess.run(["docker", "cp", hostcfg, f"{CONTAINER}:{cfg_path}"],
                       check=True, capture_output=True)
        out = subprocess.run(
            ["docker", "exec", CONTAINER, "bash", "-c",
             f"cd /home/workspace/tools/booksim2/src && ./booksim {cfg_path}"],
            capture_output=True, text=True)
    m = _DURATION.search(out.stdout)
    if not m:
        raise RuntimeError(f"booksim output unparsable:\n{out.stdout[-2000:]}"
                           f"\n{out.stderr[-500:]}")
    cycles = int(m.group(1))
    return {"cycles": cycles, "seconds": cycles * CHANNEL_CYCLE_S}


def run_per_packet_serial(flows, k=MESH_K):
    """The pessimistic identity: every packet alone in the network, times
    summed -- round-serialized by construction, no patch semantics."""
    total = 0
    for s, d, n in flows:
        r = run_batch([(s, d, 1)], k=k)
        total += n * r["cycles"]
    return {"cycles": total, "seconds": total * CHANNEL_CYCLE_S}


def lam(t_book_s, t_opt_s, t_pess_s, completion_s=None):
    """The slack coefficient under the pre-registered guard: reported
    only where the bracket is wider than 10% of completion; narrow
    brackets report the absolute deviation instead."""
    width = t_pess_s - t_opt_s
    comp = completion_s if completion_s is not None else t_book_s
    if width <= LAMBDA_GUARD_FRAC * comp:
        return {"reported": "absolute", "abs_dev_s": t_book_s - t_opt_s,
                "bracket_width_s": width}
    return {"reported": "lambda",
            "lambda": (t_book_s - t_opt_s) / width,
            "bracket_width_s": width}


def flit_bounds(flows, k=MESH_K):
    """The bridge-caliber reference bounds (cycles): busiest mesh channel
    (x-first XY, non-dedup unicasts) and the busiest injection channel --
    day-2 rails use max() of these consistently on both ends."""
    seg = {}
    inj = {}
    for s, d, n in flows:
        sx, sy = s % k, s // k
        dx, dy = d % k, d // k
        x, y = sx, sy
        path = []
        while x != dx:
            step = 1 if dx > x else -1
            path.append((("h", min(x, x + step), y)))
            x += step
        while y != dy:
            step = 1 if dy > y else -1
            path.append((("v", x, min(y, y + step))))
            y += step
        for e in path:
            seg[e] = seg.get(e, 0) + n * PACKET_FLITS
        inj[s] = inj.get(s, 0) + n * PACKET_FLITS
    return {"channel_bound_cycles": max(seg.values(), default=0),
            "injection_bound_cycles": max(inj.values(), default=0)}
