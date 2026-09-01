"""Figure rules shared by the analysis scripts (C28, 2026-08-28).

Rule -- identical series are merged or annotated, never stacked silently.
On the fill-exact 2x4 grid the three routed schemes tie exactly (centre,
corner and tree all put 4 macros' traffic on the busiest wire), and a plot
with three coincident curves shows one colour: a reader assumes two curves
are missing. `group_identical` finds the series that coincide (within a
relative tolerance); the helpers draw ONE line per group with a merged label
and an on-figure note, and bracket tied bars.
"""
import numpy as np

TIE_NOTE = "identical on this grid"


def group_identical(series, rtol=1e-6, atol=0.0):
    """series: iterable of (label, values). Returns [(labels, values)] in
    first-appearance order; two series belong together when allclose."""
    groups = []
    for label, ys in series:
        ys = np.asarray(ys, dtype=float)
        for g in groups:
            if ys.shape == g[1].shape and np.allclose(ys, g[1], rtol=rtol, atol=atol):
                g[0].append(label)
                break
        else:
            groups.append(([label], ys))
    return groups


def merged_label(labels, note=TIE_NOTE):
    return labels[0] if len(labels) == 1 else " = ".join(labels) + f" ({note})"


def plot_grouped(ax, x, series, colors=None, note=TIE_NOTE, annotate=True,
                 legend=True, at=0.5, **kw):
    """One line per identical group, coloured like the group's first member.
    Groups of two or more get a small on-figure note at fraction `at` of x."""
    out = []
    x = np.asarray(x, dtype=float)
    for labels, ys in group_identical(series):
        c = (colors or {}).get(labels[0])
        line, = ax.plot(x, ys, color=c, label=(merged_label(labels, note) if legend else "_nolegend_"), **kw)
        out.append((labels, line))
        if annotate and len(labels) > 1:
            k = int(len(x) * at)
            ax.annotate(f"{len(labels)} series identical", (x[k], ys[k]),
                        textcoords="offset points", xytext=(6, 7), fontsize=6.5,
                        color=line.get_color())
    return out


def annotate_bar_ties(ax, xs, values, rtol=1e-6, text=TIE_NOTE, min_run=2,
                      skip_value=None, dy=0.04, fontsize=6.5, color="0.3"):
    """Bracket runs of consecutive bars with equal heights and label them.
    `skip_value` (e.g. 1.0 for multipliers) leaves trivial ties unmarked."""
    xs = list(xs); values = list(values)
    runs, i = [], 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and np.isclose(values[j + 1], values[i], rtol=rtol):
            j += 1
        if j - i + 1 >= min_run and not (skip_value is not None and np.isclose(values[i], skip_value, rtol=rtol)):
            runs.append((i, j))
        i = j + 1
    ymax = max(values) if values else 1.0
    for i, j in runs:
        y = values[i] + dy * ymax
        ax.plot([xs[i], xs[j]], [y, y], "-", color=color, lw=0.9)
        ax.text((xs[i] + xs[j]) / 2, y, f" {text} ", ha="center", va="bottom",
                fontsize=fontsize, color=color)
    return runs


def merge_point_labels(points, rtol=1e-9):
    """points: [(label, x, y)] -> [(merged label, x, y)] for coincident points."""
    out = []
    for label, x, y in points:
        for o in out:
            if np.isclose(x, o[1], rtol=rtol) and np.isclose(y, o[2], rtol=rtol):
                o[0].append(label)
                break
        else:
            out.append([[label], x, y])
    return [(merged_label(ls), x, y) for ls, x, y in out]
