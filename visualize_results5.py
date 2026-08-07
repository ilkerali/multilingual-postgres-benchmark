#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
visualize_results5.py
=====================
Publication figures for the multilingual storage-model benchmark.

The script contains no hard-coded measurements. It reads the CSV emitted by
benchmark_runner_5.py, so the figures cannot drift out of sync with the tables
in the paper.

Primary metric: CLIENT-SIDE MEDIAN latency (METRIC = "client"), matching Table 4.
Set METRIC = "server" to reproduce the Appendix C1 view instead.

Changes relative to visualize_results4.py
-----------------------------------------
1.  Figure 8 now compares client-side and server-side timing for Q1 (COUNT),
    across all three dataset sizes, instead of Q3a at 1M only.

    The earlier figure was built around a fivefold divergence in Model 3's
    full substring scan. That divergence was a consequence of index bloat in
    the contaminated measurement and no longer exists: for Q3a the two measures
    now agree within 2-35% in every model. The instrumentation overhead is still
    present, but it has moved to Q1, where server-side time is 1.45-2.13 times
    client-side time uniformly across all four models and all three dataset
    sizes. Because the effect is systematic rather than confined to one model,
    it makes the methodological argument more convincingly than the original.

2.  If no CSV path is given, the most recent results2/benchmark_*.csv is used.

3.  All comments and docstrings are in English.

Usage
-----
    python visualize_results5.py
    python visualize_results5.py results2/benchmark_20260806_032855.csv
    python visualize_results5.py results2/benchmark_20260806_032855.csv server
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# ---------------------------------------------------------------------------
# 1. Configuration
# ---------------------------------------------------------------------------

RESULTS_DIR = "results2"
CSV_GLOB = "benchmark_*.csv"          # newest match is used when no path is given

# The results folder is looked up first relative to the current working
# directory, then relative to this script's own folder. Editors and IDEs often
# launch a script from the project root rather than from the file's directory,
# so relying on the working directory alone is fragile.
SCRIPT_DIR = Path(__file__).resolve().parent
METRIC = "client"                     # "client" -> Table 4 | "server" -> Table C1
OUTDIR = "figures"
DPI = 300
RADAR_LOG = True                      # normalise radar axes on a log scale
COLOUR_CAP = 4.0                      # colour saturates at COLOUR_CAP x the fastest

# Query compared in Figure 8. Q1 is used because the instrumentation overhead of
# EXPLAIN (ANALYZE, TIMING) scales with the number of rows processed, and Q1
# processes many rows while doing the least work per row.
CLI_SRV_QUERY = "q1_count_all"
CLI_SRV_LABEL = "Q1 COUNT(*)"

# CSV column stem -> label used in the figures.
# Labels match the query identifiers in Appendix B so a reader can map any bar
# in a figure straight to the SQL that produced it.
QUERIES = {
    "q1_count_all":          "Q1 COUNT",
    "q2_price_filter":       "Q2 Price",
    "q3_count_lang_filter":  "Q3a Lang (scan)",
    "q3_limit_lang_filter":  "Q3b Lang (LIMIT)",
    "q4_all_languages":      "Q4 All Langs",
    "q5_update_price":       "Q5 Upd Price",
    "q6_update_translation": "Q6 Upd Trans",
    "q7_insert_products":    "Q7 Insert",
}

# Output filenames carry the figure numbers used in the paper.
# If the numbering changes, edit ONLY this dictionary.
FIGFILE = {
    "bars":       "fig05_grouped_bar_chart.png",
    "lines":      "fig06_line_charts.png",
    "langfilt":   "fig07_language_filter.png",
    "cliserv":    "fig08_client_vs_server_q1.png",
    "storage":    "fig09_storage_footprint.png",
    "heatmap":    "fig10_heatmap.png",
    "radar":      "fig11_radar_chart.png",
    "table":      "table_results.png",        # for the repository README, not the paper
    "table_html": "table_results.html",
}

METRIC_SUFFIX = {"client": "_median", "server": "_srv_median"}
METRIC_TITLE = {
    "client": "client-side median latency, 30 iterations",
    "server": "server-side execution time, single EXPLAIN ANALYZE",
}

FLOOR = 1e-5      # floor for log scales; only needed for zero-valued server times


def relative_scale(values, cap=COLOUR_CAP):
    """Map a group of latencies onto a 0..1 colour ratio.

    Uses the ratio to the fastest value in the group rather than min-max
    normalisation: 0 = fastest, 1 = cap times slower or worse. Min-max would
    stretch practically equivalent values (say 0.0598 s and 0.0617 s) across the
    whole green-to-red range and imply a difference that does not exist.
    """
    v = np.clip(np.asarray(values, dtype=float), FLOOR, None)
    lo = v.min()
    if lo <= 0 or not np.isfinite(lo):
        return np.full(v.shape, 0.5)
    return np.clip(np.log10(v / lo) / np.log10(cap), 0.0, 1.0)


# ---------------------------------------------------------------------------
# 2. Load
# ---------------------------------------------------------------------------

def search_roots():
    """Candidate base folders, in priority order, without duplicates."""
    roots, seen = [], set()
    for root in (Path.cwd(), SCRIPT_DIR):
        resolved = root.resolve()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)
    return roots


def locate_results():
    """Find the results folder and the newest benchmark CSV inside it.

    Returns (csv_path, base_dir). base_dir is the parent of the results folder
    and is where the figures directory will be created, so output lands next to
    the input regardless of where the script was launched from.
    """
    for root in search_roots():
        folder = root / RESULTS_DIR
        if not folder.is_dir():
            continue
        found = sorted(folder.glob(CSV_GLOB),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if found:
            return str(found[0]), root
    return None, SCRIPT_DIR


def load(csv_path: str, metric: str) -> pd.DataFrame:
    """Read the CSV and reduce it to the columns of the selected metric."""
    if metric not in METRIC_SUFFIX:
        raise ValueError(f"METRIC must be 'client' or 'server', got '{metric}'.")

    raw = pd.read_csv(csv_path)
    suffix = METRIC_SUFFIX[metric]

    missing = [c + suffix for c in QUERIES if c + suffix not in raw.columns]
    if missing:
        raise KeyError(
            "Columns missing from the CSV: " + ", ".join(missing) +
            "\nThis file may have been produced by an older runner version."
        )

    df = raw[["model", "schema", "num_products"]].copy()
    for col, label in QUERIES.items():
        df[label] = raw[col + suffix].astype(float)

    empty = [lbl for lbl in QUERIES.values() if df[lbl].isna().all()]
    if empty:
        raise ValueError(
            f"Metric '{metric}' is empty in this CSV: " + ", ".join(empty) +
            "\nThe run probably predates client-side timing. Use the main run's CSV."
        )
    df[list(QUERIES.values())] = df[list(QUERIES.values())].fillna(FLOOR)

    for col in ("storage_table_mb", "storage_index_mb", "storage_total_mb"):
        if col in raw.columns:
            df[col] = raw[col].astype(float)

    return df.sort_values(["model", "num_products"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. Figures
# ---------------------------------------------------------------------------

def fig_grouped_bars(df, labels, sizes, models, outdir, subtitle):
    """Figure 5 - grouped bars, one panel per dataset size."""
    fig, axes = plt.subplots(1, len(sizes), figsize=(22, 6.5), sharey=True)
    axes = np.atleast_1d(axes)
    palette = sns.color_palette("colorblind", len(labels))

    for ax, size in zip(axes, sizes):
        subset = df[df["num_products"] == size].set_index("model")
        x = np.arange(len(models))
        width = 0.9 / len(labels)
        for j, label in enumerate(labels):
            vals = np.clip(subset.loc[models, label].to_numpy(), FLOOR, None)
            ax.bar(x + j * width, vals, width, label=label, color=palette[j])
        ax.set_xticks(x + width * (len(labels) - 1) / 2)
        ax.set_xticklabels([f"Model {m}" for m in models])
        ax.set_yscale("log")
        ax.set_title(f"{size:,} products")
        ax.grid(axis="y", which="both", alpha=0.25)
        ax.set_axisbelow(True)

    axes[0].set_ylabel("Latency (s, log scale)")
    handles, lgd = axes[0].get_legend_handles_labels()
    fig.legend(handles, lgd, loc="lower center", ncol=len(labels), frameon=False)
    fig.suptitle(f"Query latency by model and dataset size\n({subtitle})", fontsize=15)
    fig.tight_layout(rect=[0, 0.07, 1, 0.94])
    fig.savefig(Path(outdir, FIGFILE["bars"]), dpi=DPI)
    plt.close(fig)


def fig_scaling_lines(df, labels, models, outdir, subtitle):
    """Figure 6 - scaling curve per query type, log-log."""
    ncols = 4
    nrows = int(np.ceil(len(labels) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(19, 4.6 * nrows))
    axes = np.atleast_1d(axes).ravel()
    palette = sns.color_palette("colorblind", len(models))

    for ax, label in zip(axes, labels):
        for c, model in enumerate(models):
            sub = df[df["model"] == model]
            ax.plot(sub["num_products"], np.clip(sub[label], FLOOR, None),
                    marker="o", linewidth=1.8, color=palette[c], label=f"Model {model}")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(label)
        ax.set_xlabel("Products")
        ax.set_ylabel("Latency (s)")
        ax.grid(True, which="both", alpha=0.25)
        ax.set_axisbelow(True)

    for ax in axes[len(labels):]:
        ax.set_visible(False)

    axes[0].legend(fontsize=8)
    fig.suptitle(f"Scalability by query type\n({subtitle})", fontsize=15)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(Path(outdir, FIGFILE["lines"]), dpi=DPI)
    plt.close(fig)


def fig_language_filter(df, sizes, models, outdir, subtitle):
    """Figure 7 - Q3a (full scan) against Q3b (early stop, LIMIT 100).

    Both variants use the same predicate; the only difference is early
    termination. The resulting gap of three to four orders of magnitude shows
    that the ranking of the models depends on which access pattern is measured.
    """
    scan_lbl, lim_lbl = QUERIES["q3_count_lang_filter"], QUERIES["q3_limit_lang_filter"]
    fig, axes = plt.subplots(1, len(sizes), figsize=(6.2 * len(sizes), 6.0))
    axes = np.atleast_1d(axes)

    for ax, size in zip(axes, sizes):
        sub = df[df["num_products"] == size].set_index("model")
        scan = np.clip(sub.loc[models, scan_lbl].to_numpy(), FLOOR, None)
        lim = np.clip(sub.loc[models, lim_lbl].to_numpy(), FLOOR, None)
        x = np.arange(len(models))

        ax.bar(x - 0.21, scan, 0.42, label="Full scan (Q3a: COUNT ... LIKE)", color="#c0392b")
        ax.bar(x + 0.21, lim, 0.42, label="Early stop (Q3b: ... LIKE ... LIMIT 100)",
               color="#27ae60")
        for xi, (a, b) in enumerate(zip(scan, lim)):
            ax.text(xi - 0.21, a * 1.15, f"{a:.4f}", ha="center", va="bottom", fontsize=9)
            ax.text(xi + 0.21, b * 1.15, f"{b:.4f}", ha="center", va="bottom", fontsize=9)

        ax.set_yscale("log")
        ax.set_ylim(min(lim.min(), scan.min()) / 3, scan.max() * 12)
        ax.set_xticks(x)
        ax.set_xticklabels([f"Model {m}" for m in models], fontsize=11)
        ax.set_title(f"{size:,} products", fontsize=13)
        ax.grid(axis="y", which="both", alpha=0.25)
        ax.set_axisbelow(True)
        ax.tick_params(labelsize=10)

    axes[0].set_ylabel("Latency (s, log scale)", fontsize=12)
    handles, lgd = axes[0].get_legend_handles_labels()
    fig.legend(handles, lgd, loc="lower center", ncol=2, frameon=False, fontsize=11)
    fig.suptitle("Language filter: full-scan cost versus early stop (LIMIT 100)\n"
                 f"identical predicate and semantics across all four models ({subtitle})",
                 fontsize=14)
    fig.tight_layout(rect=[0, 0.07, 1, 0.90])
    fig.savefig(Path(outdir, FIGFILE["langfilt"]), dpi=DPI)
    plt.close(fig)


def fig_client_vs_server(csv_path, models, sizes, outdir):
    """Figure 8 - instrumentation overhead in server-side timing.

    EXPLAIN (ANALYZE, TIMING) instruments every row processed by every plan
    node, so its overhead scales with row count and is largest on queries that
    process many rows while doing little work per row. Q1 is exactly that case.
    The ratio is uniform across models, so it does not distort their relative
    ranking, but it does inflate absolute figures - which is why client-side
    median latency is the primary metric of this study.
    """
    raw = pd.read_csv(csv_path)
    cli_col, srv_col = f"{CLI_SRV_QUERY}_median", f"{CLI_SRV_QUERY}_srv_median"
    if cli_col not in raw.columns or srv_col not in raw.columns:
        return False

    fig, axes = plt.subplots(1, len(sizes), figsize=(5.6 * len(sizes), 5.4))
    axes = np.atleast_1d(axes)

    for ax, size in zip(axes, sizes):
        sub = raw[raw["num_products"] == size].set_index("model")
        cli = sub.loc[models, cli_col].to_numpy()
        srv = sub.loc[models, srv_col].to_numpy()
        x = np.arange(len(models))

        ax.bar(x - 0.2, cli, 0.4, label="Client-side median (Table 4)", color="#2c7fb8")
        ax.bar(x + 0.2, srv, 0.4, label="Server-side EXPLAIN ANALYZE (Table C1)",
               color="#d95f0e")
        for xi, (c, s) in enumerate(zip(cli, srv)):
            ax.text(xi - 0.2, c, f"{c:.4f}", ha="center", va="bottom", fontsize=8)
            ax.text(xi + 0.2, s, f"{s:.4f}", ha="center", va="bottom", fontsize=8)
            if c > 0:
                ax.text(xi, max(c, s) * 1.14, f"{s / c:.2f}x", ha="center",
                        va="bottom", fontsize=10, fontweight="bold", color="#444444")

        ax.set_xticks(x)
        ax.set_xticklabels([f"Model {m}" for m in models], fontsize=10)
        ax.set_title(f"{size:,} products", fontsize=12)
        ax.set_ylim(0, max(cli.max(), srv.max()) * 1.32)
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)

    axes[0].set_ylabel("Latency (s)", fontsize=11)
    handles, lgd = axes[0].get_legend_handles_labels()
    fig.legend(handles, lgd, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.suptitle(f"{CLI_SRV_LABEL}: instrumentation overhead in server-side timing\n"
                 "the ratio is systematic across models and dataset sizes",
                 fontsize=13)
    fig.tight_layout(rect=[0, 0.07, 1, 0.90])
    fig.savefig(Path(outdir, FIGFILE["cliserv"]), dpi=DPI)
    plt.close(fig)
    return True


def fig_storage(df, sizes, models, outdir):
    """Figure 9 - on-disk footprint per model, table heap and indexes separated.

    Measured before the write workload runs, so the figures contain no bloat
    from the update and insert queries.
    """
    if "storage_table_mb" not in df.columns:
        return False

    fig, axes = plt.subplots(1, len(sizes), figsize=(5.6 * len(sizes), 5.6))
    axes = np.atleast_1d(axes)

    for ax, size in zip(axes, sizes):
        sub = df[df["num_products"] == size].set_index("model")
        heap = sub.loc[models, "storage_table_mb"].to_numpy()
        idx = sub.loc[models, "storage_index_mb"].to_numpy()
        x = np.arange(len(models))

        ax.bar(x, heap, 0.6, label="Table heap", color="#34699a")
        ax.bar(x, idx, 0.6, bottom=heap, label="Indexes", color="#f0a04b")
        for xi, (h, i) in enumerate(zip(heap, idx)):
            total = h + i
            ax.text(xi, total * 1.02, f"{total:,.0f}", ha="center", va="bottom",
                    fontsize=10, fontweight="bold")
            if h > total * 0.12:
                ax.text(xi, h / 2, f"{h:,.0f}", ha="center", va="center",
                        fontsize=9, color="white")
            if i > total * 0.12:
                ax.text(xi, h + i / 2, f"{i:,.0f}", ha="center", va="center",
                        fontsize=9, color="white")

        ax.set_xticks(x)
        ax.set_xticklabels([f"Model {m}" for m in models], fontsize=11)
        ax.set_title(f"{size:,} products", fontsize=13)
        ax.set_ylim(0, (heap + idx).max() * 1.16)
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)
        ax.tick_params(labelsize=10)

    axes[0].set_ylabel("On-disk size (MB)", fontsize=12)
    handles, lgd = axes[0].get_legend_handles_labels()
    fig.legend(handles, lgd, loc="lower center", ncol=2, frameon=False, fontsize=11)
    fig.suptitle("On-disk storage footprint per model\n"
                 "measured before the write workload; labels in MB", fontsize=14)
    fig.tight_layout(rect=[0, 0.07, 1, 0.90])
    fig.savefig(Path(outdir, FIGFILE["storage"]), dpi=DPI)
    plt.close(fig)
    return True


def fig_heatmap(df, labels, sizes, models, outdir, subtitle):
    """Figure 10 - heatmap.

    Colour is assigned within each (query, size) column, so it compares models
    rather than dataset sizes. Cell values are the actual latencies in seconds.
    """
    cols, values = [], {}
    for label in labels:
        for size in sizes:
            key = f"{label}\n{size//1000}k" if size < 10**6 else f"{label}\n1M"
            cols.append(key)
            col = df[df["num_products"] == size].set_index("model").loc[models, label]
            values[key] = col.to_numpy()

    raw = pd.DataFrame(values, index=[f"Model {m}" for m in models])[cols]
    norm = raw.apply(lambda s: pd.Series(relative_scale(s), index=s.index))
    annot = raw.map(lambda v: f"{v:.4f}")

    fig, ax = plt.subplots(figsize=(0.62 * len(cols) + 4, 4.2))
    sns.heatmap(
        norm, annot=annot, fmt="", cmap="RdYlGn_r", linewidths=0.5, linecolor="white",
        vmin=0, vmax=1, annot_kws={"fontsize": 7}, ax=ax,
        cbar_kws={"label": f"x slower than fastest (green = 1x, red = {COLOUR_CAP:g}x+)"},
    )
    ax.set_title(f"Query performance heatmap\n"
                 f"({subtitle}; colour = ratio to fastest model in each column)", fontsize=13)
    ax.set_xlabel("")
    ax.set_ylabel("")
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)
    fig.tight_layout()
    fig.savefig(Path(outdir, FIGFILE["heatmap"]), dpi=DPI)
    plt.close(fig)


def fig_radar(df, labels, models, outdir, subtitle, largest):
    """Figure 11 - normalised performance on the largest dataset (1 = fastest)."""
    sub = df[df["num_products"] == largest].set_index("model")
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(8.5, 8.5), subplot_kw={"polar": True})
    palette = sns.color_palette("colorblind", len(models))

    for c, model in enumerate(models):
        scores = []
        for label in labels:
            col = np.clip(sub[label].to_numpy(), FLOOR, None)
            val = np.clip(sub.loc[model, label], FLOOR, None)
            if RADAR_LOG:
                col, val = np.log10(col), np.log10(val)
            lo, hi = col.min(), col.max()
            scores.append(1.0 if hi == lo else (hi - val) / (hi - lo))
        scores += scores[:1]
        ax.plot(angles, scores, color=palette[c], linewidth=2, label=f"Model {model}")
        ax.fill(angles, scores, color=palette[c], alpha=0.08)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_rlabel_position(248)
    scale = "log-scaled" if RADAR_LOG else "linear"
    ax.set_title(f"Normalised performance at {largest:,} products\n"
                 f"1 = fastest, 0 = slowest ({scale} per axis)\n{subtitle}",
                 size=12, y=1.09)
    ax.legend(loc="upper right", bbox_to_anchor=(1.16, 1.12), frameon=False, fontsize=9)
    fig.subplots_adjust(left=0.12, right=0.86, top=0.82, bottom=0.08)
    fig.savefig(Path(outdir, FIGFILE["radar"]), dpi=DPI)
    plt.close(fig)


def fig_table(df, labels, outdir, subtitle):
    """Colour-coded result table (PNG + HTML) for the repository README.

    Colour and the best-value marker are computed within each dataset size, so
    the 10k rows do not automatically come out as the fastest everywhere.
    """
    disp = df[["model", "schema", "num_products"] + labels].copy()

    ratio = pd.DataFrame(index=disp.index, columns=labels, dtype=float)
    best = pd.DataFrame(False, index=disp.index, columns=labels)
    for _, idx in disp.groupby("num_products").groups.items():
        block = disp.loc[idx, labels]
        for label in labels:
            ratio.loc[idx, label] = relative_scale(block[label])
        rounded = block.round(4)
        best.loc[idx] = rounded.eq(rounded.min())

    # ---- HTML ----
    html_df = disp.copy()
    html_df["num_products"] = html_df["num_products"].map("{:,}".format)
    for label in labels:
        html_df[label] = [("* " if b else "") + f"{v:.4f}"
                          for v, b in zip(disp[label], best[label])]

    def paint(_, label):
        return [f"background-color: rgba({int(r*255)}, {int((1-r)*255)}, 0, 0.55);"
                for r in ratio[label]]

    styler = html_df.style.hide(axis="index")
    for label in labels:
        styler = styler.apply(paint, label=label, subset=[label])
    styler = styler.set_caption(
        f"Benchmark results ({subtitle}). * = fastest at that dataset size; "
        "colour = ratio to that fastest value.")
    Path(outdir, FIGFILE["table_html"]).write_text(styler.to_html(), encoding="utf-8")

    # ---- PNG ----
    columns = ["model", "schema", "num_products"] + labels
    text = [[str(r["model"]), r["schema"], f"{r['num_products']:,}"] +
            [("* " if best.loc[i, l] else "") + f"{r[l]:.4f}" for l in labels]
            for i, r in disp.iterrows()]
    colours = [["#e8e8e8"] * 3 +
               [(ratio.loc[i, l], 1 - ratio.loc[i, l], 0, 0.55) for l in labels]
               for i in disp.index]

    fig, ax = plt.subplots(figsize=(2.0 + 1.35 * len(columns), 0.34 * len(text) + 1.2))
    ax.axis("off")
    table = ax.table(cellText=text, colLabels=columns, cellColours=colours,
                     loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    for j in range(len(columns)):
        table[(0, j)].set_facecolor("#2c3e50")
        table[(0, j)].set_text_props(weight="bold", color="white")
    table.scale(1.1, 1.45)
    ax.set_title(f"Benchmark results ({subtitle})\n"
                 "* = fastest at that dataset size; colour = ratio to that fastest value",
                 fontsize=11, pad=10)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.86, bottom=0.02)
    fig.savefig(Path(outdir, FIGFILE["table"]), dpi=DPI, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------------------

def main():
    metric = sys.argv[2] if len(sys.argv) > 2 else METRIC

    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
        base_dir = Path(csv_path).resolve().parent.parent
    else:
        csv_path, base_dir = locate_results()

    if not csv_path:
        looked = "\n".join(f"  {r / RESULTS_DIR}" for r in search_roots())
        sys.exit(f"No '{CSV_GLOB}' found. Looked in:\n{looked}\n\n"
                 f"Run benchmark_runner_5.py first, or pass the CSV path "
                 f"explicitly:\n  python {Path(__file__).name} "
                 f"path/to/benchmark.csv")
    if not Path(csv_path).exists():
        sys.exit(f"CSV not found: {csv_path}")

    try:
        df = load(csv_path, metric)
    except (KeyError, ValueError) as exc:
        sys.exit(str(exc))

    labels = list(QUERIES.values())
    models = sorted(df["model"].unique())
    sizes = sorted(df["num_products"].unique())
    subtitle = METRIC_TITLE[metric]

    outdir = Path(base_dir) / OUTDIR
    outdir.mkdir(parents=True, exist_ok=True)

    sns.set_style("whitegrid")
    plt.rcParams["font.size"] = 10

    produced = []
    fig_grouped_bars(df, labels, sizes, models, outdir, subtitle)
    produced.append(("Figure 5", FIGFILE["bars"]))
    fig_scaling_lines(df, labels, models, outdir, subtitle)
    produced.append(("Figure 6", FIGFILE["lines"]))
    fig_language_filter(df, sizes, models, outdir, subtitle)
    produced.append(("Figure 7", FIGFILE["langfilt"]))
    if fig_client_vs_server(csv_path, models, sizes, outdir):
        produced.append(("Figure 8", FIGFILE["cliserv"]))
    if fig_storage(df, sizes, models, outdir):
        produced.append(("Figure 9", FIGFILE["storage"]))
    fig_heatmap(df, labels, sizes, models, outdir, subtitle)
    produced.append(("Figure 10", FIGFILE["heatmap"]))
    fig_radar(df, labels, models, outdir, subtitle, max(sizes))
    produced.append(("Figure 11", FIGFILE["radar"]))
    fig_table(df, labels, outdir, subtitle)
    produced.append(("(README)", FIGFILE["table"]))
    produced.append(("(README)", FIGFILE["table_html"]))

    print(f"Source  : {csv_path}")
    print(f"Metric  : {metric} ({subtitle})")
    print(f"Coverage: {len(models)} models x {len(sizes)} dataset sizes = {len(df)} rows")
    print(f"Output  : {outdir.resolve()}\n")
    for tag, name in produced:
        print(f"  {tag:<10} {name}")


if __name__ == "__main__":
    main()
