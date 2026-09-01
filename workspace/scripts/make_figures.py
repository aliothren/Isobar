"""One driver for every figure: run the committed analyses, collect the PNGs.

Usage (inside the container, from /home/workspace/scripts):

    python3 make_figures.py all                    # every stage, sequential
    python3 make_figures.py heatmap system         # just these stages
    python3 make_figures.py --tag 3x3 system evl heatmap
    CIMSIM_FABRIC=/home/workspace/models/fabric/mlx300_3x3.yaml \\
        python3 make_figures.py --tag 3x3 system evl heatmap

Stages and what they produce (all under /home/workspace/analysis):

    system   analyze_system_gpt2 (prefill + decode) -> gpt2_system_comparison_*.png,
             gpt2_system_totals_*.json, gpt2_system_mappings_*.txt      (~45 min)
    evl      analyze_energy_vs_latency -> energy_vs_latency.png         (~10 min)
    seqlen   analyze_seqlen_kv -> attention_share_vs_seqlen.png,
             kv_cache_vs_genlen.png, energy_with_without_kv.png         (~25 min)
    heatmap  ffn1 run + crossbar_comm.summarize_and_plot
             -> crossbar_comm_heatmap.png                               (~8 min)
    region   analyze_region_locality (compute+plot) -> region_locality_vw.png (fast)
    posaware analyze_position_aware resnet18 -> resnet18_settings_compare.png
             (fabric-INdependent: phase-1 arch, place_fn priors)
    value    analyze_crossbar_value_compare -> crossbar_value_device_compare.png
             (fabric-independent)                                       (~30 min)

--tag NAME: for config-variant comparisons. Canonical outputs are snapshotted
first, each stage's outputs are then renamed to <stem>_NAME.<ext>, and the
canonical files are restored -- so a variant run never clobbers the defaults.

Everything runs SEQUENTIALLY (one mapper at a time; keep it that way).
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "analysis")

STAGES = {
    "system": {
        "cmds": [["python3", "analyze_system_gpt2.py", "512", "prefill"],
                 ["python3", "analyze_system_gpt2.py", "512", "decode"]],
        "outputs": ["gpt2_system_comparison_prefill.png",
                    "gpt2_system_comparison_decode.png",
                    "gpt2_system_totals_prefill.json",
                    "gpt2_system_totals_decode.json"],
    },
    "evl": {
        "cmds": [["python3", "analyze_energy_vs_latency.py"]],
        "outputs": ["energy_vs_latency.png"],
    },
    "seqlen": {
        "cmds": [["python3", "analyze_seqlen_kv.py"]],
        "outputs": ["attention_share_vs_seqlen.png", "kv_cache_vs_genlen.png",
                    "energy_with_without_kv.png"],
    },
    "heatmap": {
        "cmds": [["python3", "-c", (
            "import sys; sys.path.insert(0, '/home/workspace')\n"
            "from scripts import llm_workload as lw\n"
            "import scripts.crossbar_comm as cc\n"
            "r = lw.run_op(lw.Op('ffn1', 'static', P=512, C=1024, M=4096),"
            " phase='prefill')\n"
            "cc.summarize_and_plot(r['output_dir'], layer_name='ffn1')\n")]],
        "outputs": ["crossbar_comm_heatmap.png"],
    },
    "region": {
        "cmds": [["python3", "analyze_region_locality.py", "compute"],
                 ["python3", "analyze_region_locality.py", "plot"]],
        "outputs": ["region_locality_vw.png"],
    },
    "posaware": {
        "cmds": [["python3", "analyze_position_aware.py", "resnet18"]],
        "outputs": ["resnet18_settings_compare.png",
                    "resnet18_settings_compare.csv"],
    },
    "anchored": {
        "cmds": [["python3", "analyze_anchored_sweep.py"]],
        "outputs": ["anchored_sweep.png", "anchored_band.png", "anchored_sweep.json"],
    },
    "d2d": {
        "cmds": [["python3", "analyze_d2d.py"]],
        "outputs": ["d2d_assignment_impact.png", "d2d_regimes.png", "d2d_segment_map.png", "d2d_impact.json"],
    },
    "offload": {
        "cmds": [["python3", "analyze_offload_contention.py"]],
        "outputs": ["offload_contention.png", "offload_contention.json"],
    },
    "scale_tiers": {
        "cmds": [["python3", "analyze_scale_tiers.py"]],
        "outputs": ["scale_tier_probe.png", "scale_tier_2p7b.png", "scale_combined.png", "scale_tiers.json"],
    },
    "gating": {
        "cmds": [["python3", "analyze_grid_gating.py"]],
        "outputs": ["grid_gating.png", "grid_gating.json"],
    },
    "sweep": {
        "cmds": [["python3", "sweep_axes.py"]],
        "outputs": ["sweep_axis_ondie.png", "sweep_axis_d2d_355m.png", "sweep_axis_d2d_2p7b.png",
                    "sweep_axis_d2d_probe.png", "sweep_axis_unit_link.png", "device_plane.png",
                    "device_plane_collapse.png", "device_fixed_terms.png", "phase_sweep.json"],
    },
    "bandwidth": {
        "cmds": [["python3", "analyze_bandwidth_sweep.py"]],
        "outputs": ["bandwidth_sweep.png"],
    },
    "value": {
        "cmds": [["python3", "analyze_crossbar_value_compare.py"]],
        "outputs": ["crossbar_value_device_compare.png"],
    },
}


def run_stage(name, tag):
    stage = STAGES[name]
    snap = {}
    if tag:
        for f in stage["outputs"]:
            p = os.path.join(OUT, f)
            if os.path.exists(p):
                snap[p] = p + ".snapshot"
                shutil.copyfile(p, snap[p])
    for cmd in stage["cmds"]:
        print(f"\n=== [{name}] {' '.join(cmd[:4])} ===", flush=True)
        subprocess.run(cmd, cwd=HERE, check=True)
    if tag:
        for f in stage["outputs"]:
            p = os.path.join(OUT, f)
            if os.path.exists(p):
                stem, ext = os.path.splitext(f)
                shutil.move(p, os.path.join(OUT, f"{stem}_{tag}{ext}"))
        for p, s in snap.items():
            shutil.move(s, p)
    for f in stage["outputs"]:
        stem, ext = os.path.splitext(f)
        final = f"{stem}_{tag}{ext}" if tag else f
        mark = "OK " if os.path.exists(os.path.join(OUT, final)) else "?? "
        print(f"  {mark}{final}")


def main():
    args = sys.argv[1:]
    tag = None
    if "--tag" in args:
        i = args.index("--tag")
        tag = args[i + 1]
        del args[i:i + 2]
    names = list(STAGES) if (not args or args == ["all"]) else args
    unknown = [n for n in names if n not in STAGES]
    if unknown:
        sys.exit(f"unknown stage(s) {unknown}; choose from {list(STAGES)}")
    fab = os.environ.get("CIMSIM_FABRIC", "(default mlx300)")
    print(f"fabric: {fab}\nstages: {names}\ntag: {tag or '(none, canonical)'}")
    for n in names:
        run_stage(n, tag)


if __name__ == "__main__":
    main()
