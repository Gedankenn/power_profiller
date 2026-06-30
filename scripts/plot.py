#!/usr/bin/env python3
"""Power Profiler data plotter — cyberpunk style.

Usage:
    python scripts/plot.py data.txt              # reads CSV, saves plot.png
    python scripts/plot.py data.txt -o grafico   # custom output name
    python scripts/plot.py data.txt --live        # live-refresh mode (pipe)
"""

import sys
import os
import argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.patches import FancyBboxPatch
import matplotlib.patheffects as pe

# ── cyberpunk style ──────────────────────────────────────────────

BG    = "#0a0a0f"
CARD  = "#12121a"
GRID  = "#1a1a2e"
WHITE = "#e0e0e0"
GREY  = "#8888aa"

CYAN   = "#00e5ff"
MAGENTA = "#ff4081"
YELLOW  = "#ffd740"
GREEN   = "#69f0ae"
ORANGE  = "#ff9100"

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor": CARD,
    "axes.edgecolor": GRID,
    "axes.labelcolor": WHITE,
    "axes.titlecolor": WHITE,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.5,
    "grid.alpha": 0.6,
    "xtick.color": GREY,
    "ytick.color": GREY,
    "text.color": WHITE,
    "font.family": "monospace",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "legend.facecolor": CARD,
    "legend.edgecolor": GRID,
    "legend.fontsize": 9,
    "savefig.facecolor": BG,
    "savefig.edgecolor": "none",
    "savefig.dpi": 200,
})

GLOW = [pe.withSimplePatchShadow((0, 0), shadow_rgbFace=BG, alpha=0.6),
        pe.Normal()]


# ── data loading ─────────────────────────────────────────────────

def load_csv(path):
    """Parse power profiler CSV. Skips header line if present."""
    raw = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) < 4:
                continue
            # skip header
            if parts[0] == "timestamp_ms":
                continue
            try:
                t  = float(parts[0])
                v  = float(parts[1])
                ma = float(parts[2])
                mw = float(parts[3])
            except ValueError:
                continue
            raw.append((t, v, ma, mw))

    if not raw:
        sys.exit("No valid data found in file.")

    arr = np.array(raw)
    t   = arr[:, 0] / 1000.0       # ms → s
    v   = arr[:, 1]                # V
    ma  = arr[:, 2]                # mA
    mw  = arr[:, 3]                # mW

    # compute accumulated energy (mWh)
    dt = np.diff(t, prepend=t[0])  # seconds between samples
    dt[0] = dt[1] if len(dt) > 1 else 1.0
    energy_mwh = np.cumsum(mw * dt / 3600.0)

    return t, v, ma, mw, energy_mwh


# ── plot generation ──────────────────────────────────────────────

def plot_all(t, v, ma, mw, energy, out_path):
    fig = plt.figure(figsize=(16, 12))

    # ── header ──
    title  = "⚡ POWER  PROFILER  —  Analysis"
    dur    = t[-1] - t[0]
    samples = len(t)
    rate    = samples / dur if dur > 0 else 0
    sub = f"{dur:.0f}s  ·  {samples} samples  ·  {rate:.0f} Hz"
    fig.suptitle(title, fontsize=18, fontweight="bold", y=0.97, color=CYAN)
    fig.text(0.5, 0.94, sub, ha="center", fontsize=10, color=GREY)

    # ── stat cards ──
    draw_stat_cards(v, ma, mw, energy)

    # ── charts ──
    ax1 = plt.subplot(3, 1, 1)
    draw_chart(ax1, t, v, CYAN, "Voltage", "V", "%.3f")

    ax2 = plt.subplot(3, 1, 2)
    draw_chart(ax2, t, ma, MAGENTA, "Current", "mA", "%.2f")

    ax3 = plt.subplot(3, 1, 3)
    draw_chart(ax3, t, mw, YELLOW, "Power", "mW", "%.2f")

    plt.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(out_path, bbox_inches="tight")
    plt.close()
    print(f"  → {out_path}")


def draw_chart(ax, x, y, color, label, unit, fmt):
    ax.plot(x, y, color=color, linewidth=1.2, path_effects=GLOW)
    ax.fill_between(x, y, alpha=0.08, color=color)

    mean = np.mean(y)
    ax.axhline(mean, color=color, linewidth=0.8, linestyle="--", alpha=0.4)

    ax.set_ylabel(f"{label} ({unit})", color=color)
    ax.tick_params(axis="y", colors=color)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: fmt % v))
    ax.set_xlabel("Time (s)")

    # stats annotation
    stats = f"mean={fmt}  max={fmt}  min={fmt}"
    ax.text(0.99, 0.95, stats % (mean, np.max(y), np.min(y)),
            transform=ax.transAxes, ha="right", va="top",
            fontsize=8, color=GREY,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=CARD, edgecolor=GRID, alpha=0.7))

    # highlight min/max points
    imax, imin = np.argmax(y), np.argmin(y)
    ax.scatter(x[imax], y[imax], color="white", s=25, zorder=5)
    ax.scatter(x[imin], y[imin], color="white", s=25, zorder=5)
    ax.annotate(fmt % y[imax], (x[imax], y[imax]),
                textcoords="offset points", xytext=(0, 8),
                fontsize=7, color=WHITE, ha="center")


def draw_stat_cards(v, ma, mw, energy):
    """Top-row stat cards inside the main figure."""
    cards = [
        ("VOLTAGE",  "%.3f V"  % np.mean(v),   "%.3f V"  % np.max(v),  CYAN),
        ("CURRENT",  "%.2f mA" % np.mean(ma),  "%.2f mA" % np.max(ma), MAGENTA),
        ("POWER",    "%.2f mW" % np.mean(mw),  "%.2f mW" % np.max(mw), YELLOW),
        ("ENERGY",   "%.3f mWh"% energy[-1],   f"{len(v)} pts",        GREEN),
    ]
    y_top = 0.90
    for i, (label, val, sub, color) in enumerate(cards):
        x = 0.07 + i * 0.23
        # val
        plt.figtext(x, y_top + 0.01, val, fontsize=16, fontweight="bold",
                    color=color, ha="left", fontfamily="monospace")
        # label
        plt.figtext(x, y_top - 0.015, label, fontsize=8, color=GREY,
                    ha="left", fontfamily="monospace", fontweight="bold",
                    alpha=0.7)
        # sub
        plt.figtext(x, y_top - 0.032, sub, fontsize=7, color=GREY,
                    ha="left", fontfamily="monospace", alpha=0.5)


def plot_compact(t, v, ma, mw, energy, out_path):
    """Single compact chart with all 3 signals overlaid + energy."""
    fig, (ax, ax_e) = plt.subplots(2, 1, figsize=(16, 8),
                                    gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle("Power Profiler  —  Compact View", fontsize=18,
                 fontweight="bold", y=0.98, color=CYAN)

    ax.plot(t, v,  color=CYAN,    linewidth=1.2, label="Voltage (V)")
    ax.plot(t, ma, color=MAGENTA, linewidth=1.2, label="Current (mA)")
    ax.plot(t, mw, color=YELLOW,  linewidth=1.2, label="Power (mW)")

    for line in ax.lines:
        line.set_path_effects(GLOW)

    ax.legend(loc="upper right", framealpha=0.8)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Value")
    ax.grid(True, alpha=0.3)

    ax_e.plot(t, energy, color=GREEN, linewidth=1.8, path_effects=GLOW)
    ax_e.fill_between(t, energy, alpha=0.1, color=GREEN)
    ax_e.set_xlabel("Time (s)")
    ax_e.set_ylabel("Energy (mWh)", color=GREEN)
    ax_e.tick_params(axis="y", colors=GREEN)

    plt.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_path, bbox_inches="tight")
    plt.close()
    print(f"  → {out_path}")


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Power Profiler — cyberpunk plotter")
    parser.add_argument("input", nargs="?", default="controle.txt",
                        help="CSV file from power profiler")
    parser.add_argument("-o", "--output", default="plot",
                        help="Output base name (without extension)")
    parser.add_argument("--compact", action="store_true",
                        help="Single combined chart instead of 3 separate")
    parser.add_argument("--live", action="store_true",
                        help="Live-refresh mode (reads from stdin pipe)")
    args = parser.parse_args()

    if args.live:
        plot_live()
    else:
        t, v, ma, mw, energy = load_csv(args.input)
        if args.compact:
            plot_compact(t, v, ma, mw, energy, f"{args.output}.png")
        else:
            plot_all(t, v, ma, mw, energy, f"{args.output}.png")


def plot_live():
    """Read streaming CSV from stdin, update plot every N points."""
    import select
    buf = []
    count = 0
    UPDATE_EVERY = 50
    OUT = "plot_live.png"

    print("Live mode — waiting for data on stdin...")

    while True:
        if select.select([sys.stdin], [], [], 0.5)[0]:
            line = sys.stdin.readline()
            if not line:
                continue  # wait for more data
            line = line.strip()
            parts = line.split(",")
            if len(parts) >= 4 and parts[0] != "timestamp_ms":
                try:
                    buf.append([float(x) for x in parts[:4]])
                except ValueError:
                    continue
        count += 1
        if count % UPDATE_EVERY == 0 and buf:
            arr = np.array(buf[-2000:])
            t = arr[:, 0] / 1000.0
            v = arr[:, 1]
            ma = arr[:, 2]
            mw = arr[:, 3]
            dt = np.diff(t, prepend=t[0])
            dt[0] = dt[1] if len(dt) > 1 else 1.0
            energy = np.cumsum(mw * dt / 3600.0)
            plot_all(t, v, ma, mw, energy, OUT)
            print(f"  ↻ updated ({len(buf)} points)")
    # note: non-blocking approach omitted for simplicity


if __name__ == "__main__":
    main()
