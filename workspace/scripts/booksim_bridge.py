"""The BookSim bridge: conversion of a hand-off's flows into a BookSim 2
batch run, and the reference bounds the result is compared with.

BookSim2 is event-level (per-flit routers, queueing, flow control); the
analytic model is rate-level (busiest-resource division). The bridge maps
one flow set onto both, so the packet-level completion time can be compared
with the analytic bounds. The BookSim binary is built from tools/booksim2
with the patches in scripts/booksim_patches/ (file-driven batch traffic,
configurable channel latency).

CONVERSION TABLE (each entry with its source):
  flit payload      8 B   (64 data bits per flit; the 2 id bits are wire
                           format -- JSSC'20 SII-C; consistent with the
                           128 B = 16-payload-flit packet)
  channel cycle     1.454545 ns = 8 B / 5.5 GB/s  (the experiment-mode
                           link rate, MICRO'19 sec. 4.1; BookSim moves one
                           flit per channel per cycle)
  hop latency       14 cycles TOTAL = channel 10 + router pipeline 4
                           (20 ns/hop, MICRO'19 Tab 2. BookSim's default IQ
                           router pipeline measures 4 cycles/hop and
                           overriding its alloc delays trips a switch-timing
                           assertion, so the alignment is channel 10 +
                           default router 4 = 14 cycles, a -1.8% optimistic
                           remainder against 20 ns.
                           Silicon's own router is 2 of the 20 ns (JSSC
                           SII-C); the split here is tool alignment, the
                           TOTAL carries the provenance)
  packet            17 flits (1 head + 16 payload = 128 B payload)
  vc_buf_size       34 flits -- aligned, not the default: the default 8
                           cannot cover the
                           14-cycle hop's bandwidth-delay product and
                           credit-throttles every channel ~2x; silicon
                           sustains the full 70 Gb/s line rate (JSSC
                           SII-C), so the reference must cover BDP too.
                           Insensitive 34 vs 64 (1.0018 in both cases).
  INJECTION CALIBER (declared): BookSim gives each node ONE injection
  channel; Simba's NoP router has FOUR NoC-side local ports. Source-
  concentrated flow sets therefore bind on the injection channel in the
  bridge's caliber; every reference uses
  ref = max(mesh-channel bound, injection bound) consistently.
  interface base    7 cycles per packet -- BRIDGE-INTERNAL measured
                           constant (BookSim itself, BDP-aligned config;
                           lone 1-hop packet = 17 + 14 + 7; the default
                           8-flit buffer read 37). No silicon
                           counterpart is claimed.
  UN-ALIGNED (BookSim defaults, declared; congestion-side only):
    num_vcs = 16, credit_delay = 2
"""
import math
import os
import re
import subprocess
import sys
import tempfile

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BOOKSIM = os.path.join(WS, "tools", "booksim2", "src", "booksim")
CONTAINER = os.environ.get("ISOBAR_CONTAINER", "isobar")      # used only when the binary cannot run on the host
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
LAMBDA_GUARD_FRAC = 0.10                           # bracket-position guard: 10% of the bracket width


def available():
    return os.path.exists(BOOKSIM)


def packets_for(volume_bytes):
    return int(math.ceil(volume_bytes / PACKET_PAYLOAD_B))


MESH_K = 6                 # the bridge's default grid (the Simba NoP)


def cmesh_address(x, y, t, k, c=4):
    """BookSim cmesh terminal address of terminal t (0..c-1) of the router at
    (x, y) on a k x k router grid with concentration c = cX x cY (cX = cY =
    sqrt(c)): address = (y cY + ty) (cX k) + (x cX + tx) -- the inverse of
    CMesh::NodeToRouter."""
    cx = int(round(c ** 0.5)); tx, ty = t % cx, t // cx
    return (y * cx + ty) * (cx * k) + (x * cx + tx)


def split_flows_kappa(flows, k, kappa):
    """kappa = c terminal channels per die: each die becomes
    a cmesh router with c terminals; a flow's packets are spread evenly over
    the c (source terminal i -> destination terminal i) pairs, so the die's
    injection and ejection capacity is c link channels while every mesh
    channel stays one link. kappa must be a perfect square (cmesh needs
    cX = cY); 4 stands in for the kappa >= 2 regime, where ports never bind."""
    c = int(kappa)
    out = []
    for s, d, n in flows:
        sx, sy, dx, dy = s % k, s // k, d % k, d // k
        for t in range(c):
            share = n // c + (1 if t < n % c else 0)
            if share:
                out.append((cmesh_address(sx, sy, t, k, c), cmesh_address(dx, dy, t, k, c), share))
    return out


def _write_config(path, flow_path, extra=None, k=MESH_K, kappa=1):
    if int(kappa) > 1:
        c = int(kappa); cx = int(round(c ** 0.5))
        assert cx * cx == c, "cmesh concentration must be a perfect square"
        # Allocators: BookSim's default separable iSLIP
        # allocator starves a shared output channel under several local
        # inputs (a 3-flow single-channel test at c = 4 reads 1.37x the
        # channel bound), while the wavefront (maximal-matching) allocator
        # reaches it (1.003x; single-flow 1.002x at either setting). The
        # concentrated runs therefore use wavefront so that the port model,
        # not the router allocator, is what differs from the kappa = 1 runs.
        lines = ["topology = cmesh;", f"k = {k};", "n = 2;", f"c = {c};", f"xr = {cx};", f"yr = {cx};",
                 "routing_function = dor_no_express;", "use_noc_latency = 0;",
                 "sw_allocator = wavefront;", "vc_allocator = wavefront;"]
    else:
        lines = ["topology = mesh;", f"k = {k};", "n = 2;", "routing_function = dor;"]
    lines += [
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
              k=MESH_K, kappa=1):
    """flows: [(src_node, dst_node, n_packets)] on a k x k mesh (node =
    y*k+x, matching the repo's row-major die table; k defaults to the
    Simba NoP's 6). Returns completion cycles (inject + drain) and
    seconds at the NoP channel cycle."""
    if not available():
        raise FileNotFoundError(
            f"{BOOKSIM} missing -- build it as described in tools/README.md")
    tag = next(tempfile._get_candidate_names())
    flow_path = f"/tmp/bsflows_{tag}"
    cfg_path = f"/tmp/bscfg_{tag}"
    with open(f"/tmp/h_{tag}", "w") as f:      # host-side scratch, copied in
        pass
    hostflow = f"/tmp/hostflows_{tag}"
    if int(kappa) > 1:
        flows = split_flows_kappa(flows, k, kappa)
    with open(hostflow, "w") as f:
        for s, d, n in flows:
            f.write(f"{s} {d} {n}\n")
    hostcfg = f"/tmp/hostcfg_{tag}"
    ex = dict(extra or {})
    if latency_channel_cycles != HOP_CHANNEL_CYCLES:
        ex.setdefault("mesh_channel_latency", latency_channel_cycles)
    if IN_CONTAINER or os.access(BOOKSIM, os.X_OK):
        # inside the container, or on a host where the vendored binary runs
        # directly (its shared libraries are the stock ones): no docker hop
        os.replace(hostflow, flow_path)
        _write_config(cfg_path, flow_path, ex, k, kappa)
        out = subprocess.run([BOOKSIM, cfg_path],
                             capture_output=True, text=True)
    else:
        _write_config(hostcfg, flow_path, ex, k, kappa)
        subprocess.run(["docker", "cp", hostflow, f"{CONTAINER}:{flow_path}"],
                       check=True, capture_output=True)
        subprocess.run(["docker", "cp", hostcfg, f"{CONTAINER}:{cfg_path}"],
                       check=True, capture_output=True)
        out = subprocess.run(
            ["docker", "exec", CONTAINER, "bash", "-c",
             f"cd /home/workspace/tools/booksim2/src && ./booksim {cfg_path}"],
            capture_output=True, text=True)
    if os.environ.get("BOOKSIM_DEBUG"):
        sys.stderr.write("[booksim stdout tail]\n" + "\n".join(out.stdout.splitlines()[-40:]) + "\n")
    m = _DURATION.search(out.stdout)
    if not m:
        raise RuntimeError(f"booksim output unparsable:\n{out.stdout[-2000:]}"
                           f"\n{out.stderr[-500:]}")
    cycles = int(m.group(1))
    res = {"cycles": cycles, "seconds": cycles * CHANNEL_CYCLE_S}
    for key, pat in (("packet_latency_avg", r"Packet latency average = ([\d.]+)"),
                     ("network_latency_avg", r"Network latency average = ([\d.]+)"),
                     ("flit_latency_avg", r"Flit latency average = ([\d.]+)"),
                     ("hops_avg", r"Hops average = ([\d.]+)")):
        mm = re.search(pat, out.stdout)
        if mm:
            res[key] = float(mm.group(1))
    return res


def run_per_packet_serial(flows, k=MESH_K):
    """The pessimistic identity: every packet alone in the network, times
    summed -- round-serialized by construction, no patch semantics."""
    total = 0
    for s, d, n in flows:
        r = run_batch([(s, d, 1)], k=k)
        total += n * r["cycles"]
    return {"cycles": total, "seconds": total * CHANNEL_CYCLE_S}


def lam(t_book_s, t_opt_s, t_pess_s, completion_s=None):
    """The slack coefficient lambda (position of the BookSim time inside the
    [optimistic, round-serialized] bracket): reported
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


def flit_bounds(flows, k=MESH_K, kappa=1):
    """The bridge-caliber reference bounds (cycles): busiest mesh channel
    (x-first XY, non-dedup unicasts) and the busiest injection channel --
    the comparisons use max() of these consistently on both ends."""
    seg = {}
    inj = {}
    ej = {}       # the ejection port is a resource too (a 2-into-1 pattern reads 2x the channel bound without it)
    for s, d, n in flows:
        sx, sy = s % k, s // k
        dx, dy = d % k, d // k
        x, y = sx, sy
        path = []
        # full-duplex channels: the two directions of a segment are
        # different channels (keyed with the direction, so opposite-direction
        # flows never share a channel)
        while x != dx:
            step = 1 if dx > x else -1
            path.append((("h", min(x, x + step), y, step)))
            x += step
        while y != dy:
            step = 1 if dy > y else -1
            path.append((("v", x, min(y, y + step), step)))
            y += step
        for e in path:
            seg[e] = seg.get(e, 0) + n * PACKET_FLITS
        inj[s] = inj.get(s, 0) + n * PACKET_FLITS
        ej[d] = ej.get(d, 0) + n * PACKET_FLITS
    return {"channel_bound_cycles": max(seg.values(), default=0),
            "injection_bound_cycles": int(math.ceil(max(inj.values(), default=0) / int(kappa))),
            "ejection_bound_cycles": int(math.ceil(max(ej.values(), default=0) / int(kappa)))}


CHECK_FLOWS = [(0, 14, 512), (1, 14, 512), (6, 20, 256)]     # (source, destination, packets) on a 6 x 6 concentrated mesh
CHECK_CYCLES = 21813                                           # completion time with the patched BookSim at the pinned commit


def check():
    """Integration check: run a small batch through the patched binary (file
    traffic, concentrated mesh, configurable channel latency) and compare it
    with the reference result."""
    if not available():
        raise SystemExit(f"{BOOKSIM} not found -- build it as described in tools/README.md")
    r = run_batch(CHECK_FLOWS, k=6, kappa=4)
    ok = r["cycles"] == CHECK_CYCLES
    print(f"BookSim batch: {r['cycles']} cycles (expected {CHECK_CYCLES}) -> {'OK' if ok else 'MISMATCH'}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        print("usage: python3 scripts/booksim_bridge.py --check")
