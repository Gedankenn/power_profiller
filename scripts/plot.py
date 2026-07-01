#!/usr/bin/env python3
"""Power Profiler plotter — cyberpunk style + burst detection + battery life.

Usage:
    python scripts/plot.py data.txt             # basic 3-chart plot
    python scripts/plot.py data.txt -o name     # custom output name
    python scripts/plot.py data.txt --analyze   # + burst analysis & battery estimate
    python scripts/plot.py data.txt --compact   # single combined chart
"""

import sys
import argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.patheffects as pe

# ── style ────────────────────────────────────────────────────────

BG     = "#0a0a0f"
CARD   = "#12121a"
GRID   = "#1a1a2e"
WHITE  = "#e0e0e0"
GREY   = "#8888aa"
CYAN   = "#00e5ff"
MAGENTA = "#ff4081"
YELLOW = "#ffd740"
GREEN  = "#69f0ae"
ORANGE = "#ff9100"
RED    = "#ff5252"

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": CARD,
    "axes.edgecolor": GRID, "axes.labelcolor": WHITE,
    "axes.titlecolor": WHITE, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.5, "grid.alpha": 0.6,
    "xtick.color": GREY, "ytick.color": GREY,
    "text.color": WHITE, "font.family": "monospace",
    "font.size": 10, "axes.titlesize": 12, "axes.labelsize": 10,
    "legend.facecolor": CARD, "legend.edgecolor": GRID,
    "legend.fontsize": 9, "savefig.facecolor": BG,
    "savefig.edgecolor": "none", "savefig.dpi": 200,
})
GLOW = [pe.withSimplePatchShadow((0, 0), shadow_rgbFace=BG, alpha=0.6),
        pe.Normal()]

# ── CR2032 model ─────────────────────────────────────────────────

def cr2032_usable_mah(avg_discharge_ma):
    """CR2032 effective mAh at a given average discharge current."""
    if avg_discharge_ma < 1:
        return 225.0
    elif avg_discharge_ma < 5:
        return 210.0
    elif avg_discharge_ma < 10:
        return 195.0
    elif avg_discharge_ma < 20:
        return 170.0
    elif avg_discharge_ma < 30:
        return 140.0
    else:
        return 100.0

# ── data loading ─────────────────────────────────────────────────

def load_csv(path):
    raw = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) < 4 or parts[0] == "timestamp_ms":
                continue
            try:
                raw.append([float(x) for x in parts[:4]])
            except ValueError:
                continue
    if not raw:
        sys.exit("No valid data found.")

    arr = np.array(raw)
    t   = arr[:, 0] / 1000.0       # ms → s
    v   = arr[:, 1]                # V
    ma  = arr[:, 2]                # mA
    mw  = arr[:, 3]                # mW

    # unwrap tick counter (32-bit overflow: detect drop, add offset)
    cum_offset = 0.0
    avg_gap = (t[-1] - t[0]) / (len(t) - 1) if len(t) > 1 else 0.02
    if avg_gap <= 0:
        avg_gap = 0.02
    for i in range(1, len(t)):
        ti = t[i] + cum_offset
        if ti < t[i - 1]:
            cum_offset += (t[i - 1] - ti) + avg_gap
        t[i] += cum_offset
    dt  = np.diff(t, prepend=t[0])
    dt[0] = dt[1] if len(dt) > 1 else 1.0
    e_cum = np.cumsum(mw * dt / 3600.0)
    return t, v, ma, mw, e_cum, dt


# ── burst detection ──────────────────────────────────────────────

def detect_bursts(t, v, ma, mw, dt, threshold=0.5, min_gap=0.15):
    """Find contiguous active periods (current > threshold).
     min_gap: merge bursts closer than this many seconds."""
    active = ma > threshold
    if not active.any():
        return [], []

    # find edges: rising (False→True) and falling (True→False)
    diff = np.diff(active.astype(int))
    starts = np.where(diff == 1)[0] + 1
    ends   = np.where(diff == -1)[0] + 1

    if active[0]:
        starts = np.insert(starts, 0, 0)
    if active[-1]:
        ends = np.append(ends, len(active))

    bursts = []
    for s, e in zip(starts, ends):
        if e - s < 2:
            continue  # skip 1-sample glitches
        dur = t[e - 1] - t[s]
        b = {
            "start_s": t[s], "end_s": t[e - 1], "duration_s": dur,
            "samples": e - s,
            "v_avg": float(np.mean(v[s:e])),
            "v_min": float(np.min(v[s:e])),
            "c_avg": float(np.mean(ma[s:e])),
            "c_max": float(np.max(ma[s:e])),
            "p_avg": float(np.mean(mw[s:e])),
            "p_max": float(np.max(mw[s:e])),
            "energy_mwh": float(np.sum(mw[s:e] * dt[s:e] / 3600.0)),
        }
        bursts.append(b)

    # merge bursts separated by < min_gap
    merged = []
    for b in bursts:
        if merged and 0 < (b["start_s"] - merged[-1]["end_s"]) < min_gap:
            prev = merged[-1]
            dur = b["end_s"] - prev["start_s"]
            prev.update({
                "end_s": b["end_s"], "duration_s": dur,
                "samples": prev["samples"] + b["samples"],
                "v_avg": (prev["v_avg"] + b["v_avg"]) / 2,
                "v_min": min(prev["v_min"], b["v_min"]),
                "c_avg": (prev["c_avg"] * prev["samples"] + b["c_avg"] * b["samples"]) / (prev["samples"] + b["samples"]),
                "c_max": max(prev["c_max"], b["c_max"]),
                "p_avg": (prev["p_avg"] * prev["samples"] + b["p_avg"] * b["samples"]) / (prev["samples"] + b["samples"]),
                "p_max": max(prev["p_max"], b["p_max"]),
                "energy_mwh": prev["energy_mwh"] + b["energy_mwh"],
            })
        else:
            merged.append(b)

    return bursts, merged


def classify_bursts(bursts):
    """Auto-split bursts into two populations by largest duration gap."""
    if len(bursts) < 4:
        return bursts, [], (None, None)

    durs = sorted([b["duration_s"] * 1000 for b in bursts])
    gaps = [(durs[i + 1] - durs[i], durs[i]) for i in range(len(durs) - 1)]
    best_gap, split_at = max(gaps, key=lambda x: x[0])

    # require at least 20% gap to be meaningful
    if best_gap < split_at * 0.2:
        return bursts, [], (None, None)

    threshold = split_at + best_gap / 2
    fast = [b for b in bursts if b["duration_s"] * 1000 < threshold]
    slow = [b for b in bursts if b["duration_s"] * 1000 >= threshold]

    label_fast = "Short"
    avg_dur_fast = np.mean([b["duration_s"] for b in fast]) * 1000 if fast else 0
    avg_dur_slow = np.mean([b["duration_s"] for b in slow]) * 1000 if slow else 0
    if avg_dur_fast > 0 and avg_dur_slow > 0:
        if avg_dur_slow / avg_dur_fast > 2.5:
            label_fast = "Legacy"
            label_slow = "Challenge"

    return fast, slow, (label_fast, label_slow or "Long")


def burst_stats(bursts, t_total_s, idle_ma):
    """Aggregate statistics from burst list."""
    n = len(bursts)
    if n == 0:
        return None

    durs  = np.array([b["duration_s"] for b in bursts])
    e_per = np.array([b["energy_mwh"] for b in bursts])
    c_max = np.array([b["c_max"] for b in bursts])
    c_avg = np.array([b["c_avg"] for b in bursts])
    v_min = np.array([b["v_min"] for b in bursts])

    # idle energy
    idle_v = 3.0
    idle_power_mw = abs(idle_ma) * idle_v  # typically near 0
    idle_energy = idle_power_mw * t_total_s / 3600.0

    total_energy = np.sum(e_per) + idle_energy
    avg_power_mw = total_energy / t_total_s * 3600.0

    return {
        "n_bursts": n,
        "duration_s_avg": float(np.mean(durs)),
        "duration_s_med": float(np.median(durs)),
        "duration_s_p95": float(np.percentile(durs, 95)),
        "energy_uj_per": float(np.mean(e_per)) * 3_600_000,   # mWh → µJ
        "energy_uj_total": float(total_energy) * 3_600_000,   # mWh → µJ
        "c_avg_avg": float(np.mean(c_avg)),
        "c_max_peak": float(np.max(c_max)),
        "v_min_global": float(np.min(v_min)),
        "avg_power_mw": float(avg_power_mw),
        "total_energy_mwh": float(total_energy),
        "idle_energy_mwh": float(idle_energy),
        "bursts_per_min": n / (t_total_s / 60.0),
        "duty_pct": float(np.sum(durs) / t_total_s * 100),
}


def estimate_battery(stats, total_seconds, presses_per_day=4):
    """Return battery life for a CR2032 — both captured pattern and normal use."""
    avg_ma = stats["avg_power_mw"] / 3.0
    usable_mah = cr2032_usable_mah(avg_ma)
    total_mwh = usable_mah * 2.9

    daily_mwh_captured = stats["total_energy_mwh"] * (86400.0 / total_seconds)
    days_captured = total_mwh / daily_mwh_captured if daily_mwh_captured > 0 else float("inf")

    energy_per_burst_mwh = stats["energy_uj_per"] / 3_600_000
    daily_mwh_normal = energy_per_burst_mwh * presses_per_day
    days_normal = total_mwh / daily_mwh_normal if daily_mwh_normal > 0 else float("inf")

    return {
        "avg_ma": avg_ma, "usable_mah": usable_mah, "total_mwh": total_mwh,
        "energy_per_burst_mwh": energy_per_burst_mwh,
        "captured": {"daily_mwh": daily_mwh_captured, "days": days_captured,
                     "months": days_captured / 30.44, "years": days_captured / 365.25},
        "normal":   {"presses_day": presses_per_day, "daily_mwh": daily_mwh_normal,
                     "days": days_normal, "months": days_normal / 30.44,
                     "years": days_normal / 365.25},
    }


# ── plot helpers ─────────────────────────────────────────────────

def draw_chart(ax, x, y, color, label, unit, fmt):
    ax.plot(x, y, color=color, linewidth=1.2, path_effects=GLOW)
    ax.fill_between(x, y, alpha=0.08, color=color)
    mean = np.mean(y)
    ax.axhline(mean, color=color, linewidth=0.8, linestyle="--", alpha=0.4)
    ax.set_ylabel(f"{label} ({unit})", color=color)
    ax.tick_params(axis="y", colors=color)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: fmt % v))
    ax.set_xlabel("Time (s)")
    stats = f"mean={fmt}  max={fmt}  min={fmt}"
    ax.text(0.99, 0.95, stats % (mean, np.max(y), np.min(y)),
            transform=ax.transAxes, ha="right", va="top",
            fontsize=8, color=GREY,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=CARD,
                      edgecolor=GRID, alpha=0.7))
    imax, imin = np.argmax(y), np.argmin(y)
    ax.scatter(x[imax], y[imax], color="white", s=25, zorder=5)
    ax.scatter(x[imin], y[imin], color="white", s=25, zorder=5)
    ax.annotate(fmt % y[imax], (x[imax], y[imax]),
                textcoords="offset points", xytext=(0, 8),
                fontsize=7, color=WHITE, ha="center")


def draw_stat_cards(v, ma, mw, energy):
    cards = [
        ("VOLTAGE",  "%.3f V" % np.mean(v),   "%.3f V"  % np.max(v),  CYAN),
        ("CURRENT",  "%.2f mA"% np.mean(ma),  "%.2f mA" % np.max(ma), MAGENTA),
        ("POWER",    "%.2f mW"% np.mean(mw),  "%.2f mW" % np.max(mw), YELLOW),
        ("ENERGY",   "%.3f mWh" % energy[-1], f"{len(v)} pts",        GREEN),
    ]
    for i, (label, val, sub, color) in enumerate(cards):
        x = 0.07 + i * 0.23
        plt.figtext(x, 0.91, val, fontsize=16, fontweight="bold",
                    color=color, ha="left", fontfamily="monospace")
        plt.figtext(x, 0.885, label, fontsize=8, color=GREY, ha="left",
                    fontfamily="monospace", fontweight="bold", alpha=0.7)
        plt.figtext(x, 0.868, sub, fontsize=7, color=GREY, ha="left",
                    fontfamily="monospace", alpha=0.5)


# ── main chart ───────────────────────────────────────────────────

def plot_all(t, v, ma, mw, energy, out_path):
    fig = plt.figure(figsize=(16, 12))
    dur = t[-1] - t[0]
    fig.suptitle("⚡ POWER PROFILER  —  Analysis", fontsize=18,
                 fontweight="bold", y=0.97, color=CYAN)
    fig.text(0.5, 0.94, f"{dur:.0f}s · {len(t)} samples · {len(t)/dur:.0f} Hz",
             ha="center", fontsize=10, color=GREY)
    draw_stat_cards(v, ma, mw, energy)

    ax1 = plt.subplot(3, 1, 1)
    draw_chart(ax1, t, v, CYAN, "Voltage", "V", "%.3f")
    ax2 = plt.subplot(3, 1, 2)
    draw_chart(ax2, t, ma, MAGENTA, "Current", "mA", "%.2f")
    ax3 = plt.subplot(3, 1, 3)
    draw_chart(ax3, t, mw, YELLOW, "Power", "mW", "%.2f")

    plt.tight_layout(rect=(0, 0, 1, 0.85))
    fig.savefig(out_path, bbox_inches="tight")
    plt.close()
    print(f"  → {out_path}")


# ── burst analysis chart ─────────────────────────────────────────

def plot_analysis(t, v, ma, mw, dt, bursts, stats, batt, out_path):
    if stats is None or len(bursts) == 0:
        # still produce a basic plot
        plot_all(t, v, ma, mw, np.cumsum(mw * dt / 3600.0), out_path.replace(".png", "_analysis.png"))
        return

    fig = plt.figure(figsize=(18, 14))
    fig.suptitle("POWER PROFILER  —  Burst Analysis & Battery Life",
                 fontsize=18, fontweight="bold", y=0.98, color=CYAN)

    # ── stat cards (top row) ──
    cards = [
        ("BURSTS",     str(stats["n_bursts"]),
                       f"{stats['bursts_per_min']:.1f}/min",         MAGENTA),
        ("AVG DURATION", f"{stats['duration_s_avg']*1000:.0f} ms",
                       f"max {stats['duration_s_p95']*1000:.0f} ms", CYAN),
        ("AVG CURRENT",   f"{stats['c_avg_avg']:.1f} mA",
                       f"peak {stats['c_max_peak']:.1f} mA",         YELLOW),
        ("BURST ENERGY",  f"{stats['energy_uj_per']:.0f} µJ",
                        f"{stats['energy_uj_total']:.0f} µJ tot", GREEN),
        ("BATTERY LIFE",  f"{batt['normal']['days']:.0f} days",
                        f"@ {batt['normal']['presses_day']:.0f} presses/day  ·  {batt['normal']['years']:.1f}y", ORANGE),
    ]
    for i, (label, val, sub, color) in enumerate(cards):
        x = 0.04 + i * 0.195
        plt.figtext(x, 0.945, val, fontsize=16, fontweight="bold",
                    color=color, ha="left", fontfamily="monospace")
        plt.figtext(x, 0.920, label, fontsize=8, color=GREY, ha="left",
                    fontfamily="monospace", fontweight="bold", alpha=0.7)
        plt.figtext(x, 0.905, sub, fontsize=7, color=GREY, ha="left",
                    fontfamily="monospace", alpha=0.5)

    # ── voltage + current trace with burst shading ──
    ax_trace = plt.subplot(2, 2, (1, 2))
    ax2 = ax_trace.twinx()

    ax_trace.plot(t, v, color=CYAN, linewidth=1.2, label="Voltage (V)", path_effects=GLOW)
    ax_trace.set_ylabel("Voltage (V)", color=CYAN)
    ax_trace.tick_params(axis="y", colors=CYAN)

    ax2.plot(t, ma, color=MAGENTA, linewidth=1.0, label="Current (mA)", alpha=0.9)
    ax2.set_ylabel("Current (mA)", color=MAGENTA)
    ax2.tick_params(axis="y", colors=MAGENTA)

    # shade burst regions
    for b in bursts:
        ax_trace.axvspan(b["start_s"], b["end_s"], color=MAGENTA, alpha=0.06, lw=0)

    ax_trace.set_xlabel("Time (s)")
    ax_trace.grid(True, alpha=0.2)

    # ── burst histogram: duration ──
    ax_dur = plt.subplot(2, 4, 5)
    durs_ms = np.array([b["duration_s"] * 1000 for b in bursts])
    bins = np.linspace(0, max(durs_ms) * 1.1, max(8, min(25, len(bursts) // 3)))
    ax_dur.hist(durs_ms, bins=bins, color=MAGENTA, alpha=0.7, edgecolor=MAGENTA, linewidth=0.5)
    ax_dur.axvline(np.mean(durs_ms), color=WHITE, linewidth=1, linestyle="--",
                   label=f"avg {np.mean(durs_ms):.0f} ms")
    ax_dur.set_xlabel("Burst duration (ms)")
    ax_dur.set_ylabel("Count")
    ax_dur.legend(fontsize=7, facecolor=CARD, edgecolor=GRID)
    ax_dur.grid(True, alpha=0.2)

    # ── burst histogram: energy ──
    ax_e = plt.subplot(2, 4, 6)
    e_uj = np.array([b["energy_mwh"] * 1000 for b in bursts])
    bins_e = np.linspace(0, max(e_uj) * 1.1, max(8, min(25, len(bursts) // 3)))
    ax_e.hist(e_uj, bins=bins_e, color=YELLOW, alpha=0.7, edgecolor=YELLOW, linewidth=0.5)
    ax_e.axvline(np.mean(e_uj), color=WHITE, linewidth=1, linestyle="--",
                 label=f"avg {np.mean(e_uj):.0f} µJ")
    ax_e.set_xlabel("Energy per burst (µJ)")
    ax_e.set_ylabel("Count")
    ax_e.legend(fontsize=7, facecolor=CARD, edgecolor=GRID)
    ax_e.grid(True, alpha=0.2)

    # ── battery life gauge ──
    ax_bat = plt.subplot(2, 4, 7)
    ax_bat.set_xlim(-1.5, 1.5)
    ax_bat.set_ylim(-1.5, 1.5)
    ax_bat.set_aspect("equal")
    ax_bat.axis("off")

    days = batt["normal"]["days"]
    if days > 365:
        pct = min(1.0, days / 730)
        label = f"{days:.0f}d"
        sub = f"{days/30.44:.0f} months"
    else:
        pct = min(1.0, days / 90)
        label = f"{days:.0f}d"
        sub = f"{days/7:.1f} weeks"

    theta = np.linspace(0, pct * 2 * np.pi, 200)
    r_inner, r_outer = 0.8, 1.2
    # background ring
    bg_theta = np.linspace(0, 2 * np.pi, 200)
    ax_bat.fill_between(np.cos(bg_theta) * 0.8, np.cos(bg_theta) * 1.0,
                        np.sin(bg_theta) * 0.8, np.sin(bg_theta) * 1.0,
                        color=GRID, alpha=0.3)
    # filled ring
    for r in np.linspace(0.8, 1.0, 20):
        ax_bat.plot(np.cos(theta) * r, np.sin(theta) * r,
                    color=GREEN, linewidth=1.5, alpha=0.15)
    # outline
    ax_bat.add_artist(plt.Circle((0, 0), 1.0, fill=False, color=GREEN, linewidth=2))
    ax_bat.text(0, 0.1, label, ha="center", va="center", fontsize=20,
                fontweight="bold", color=GREEN, fontfamily="monospace")
    ax_bat.text(0, -0.35, sub, ha="center", va="center", fontsize=9,
                color=GREY, fontfamily="monospace")

    # ── battery info text ──
    ax_info = plt.subplot(2, 4, 8)
    ax_info.axis("off")
    info_lines = [
        f"Battery: CR2032",
        f"",
        f"Capacity: {batt['usable_mah']:.0f} mAh",
        f"  at {batt['avg_ma']:.2f} mA avg",
        f"",
        f"Usable energy: {batt['total_mwh']:.0f} mWh",
        f"Energy/burst:  {batt['energy_per_burst_mwh']*1000:.0f} µJ",
        f"",
        f"Captured (test)",
        f"  {batt['captured']['days']:.0f} d · {batt['captured']['months']:.0f} mo",
        f"",
        f"Normal use",
        f"  {batt['normal']['presses_day']:.0f} presses/day",
        f"  {batt['normal']['days']:.0f} d · {batt['normal']['months']:.0f} mo",
        f"  {batt['normal']['years']:.1f} years",
    ]
    for j, line in enumerate(info_lines):
        color = GREEN if j == 0 or j >= 8 else GREY
        size = 12 if j == 0 else 9
        ax_info.text(0.05, 0.95 - j * 0.07, line, transform=ax_info.transAxes,
                     fontsize=size, color=color, fontfamily="monospace",
                     fontweight="bold" if color == GREEN else "normal")

    plt.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(out_path, bbox_inches="tight")
    plt.close()
    print(f"  → {out_path}")


def plot_dual_analysis(t, v, ma, mw, dt, fast, slow, labels,
                        stats_fast, batt_fast, stats_slow, batt_slow, out_path):
    """Dual burst-type analysis: legacy vs challenge side-by-side."""
    fig = plt.figure(figsize=(20, 14))
    lab_f, lab_s = labels
    title = f"POWER PROFILER  —  Dual Burst Analysis: {lab_f} vs {lab_s}"
    fig.suptitle(title, fontsize=17, fontweight="bold", y=0.98, color=CYAN)

    # ── top stat cards ──
    cards = [
        (lab_f.upper(),   f"{len(fast)} bursts",
                          f"{stats_fast['duration_s_avg']*1000:.0f} ms avg  ·  {stats_fast['energy_uj_per']:.0f} µJ/burst", CYAN),
        (lab_s.upper(),   f"{len(slow)} bursts",
                          f"{stats_slow['duration_s_avg']*1000:.0f} ms avg  ·  {stats_slow['energy_uj_per']:.0f} µJ/burst", MAGENTA),
        (f"{lab_f} BATTERY", f"{batt_fast['normal']['days']:.0f} days",
                          f"{batt_fast['normal']['years']:.1f} years  @ 4 presses/day", CYAN),
        (f"{lab_s} BATTERY", f"{batt_slow['normal']['days']:.0f} days",
                          f"{batt_slow['normal']['years']:.1f} years  @ 4 presses/day", MAGENTA),
        ("TOTAL ENERGY",  f"{stats_fast['energy_uj_total']+stats_slow['energy_uj_total']:.0f} µJ",
                          f"{len(fast)+len(slow)} bursts  ·  {stats_fast['bursts_per_min']+stats_slow['bursts_per_min']:.1f}/min", YELLOW),
    ]
    for i, (label, val, sub, color) in enumerate(cards):
        x = 0.03 + i * 0.195
        plt.figtext(x, 0.945, val, fontsize=14, fontweight="bold",
                    color=color, ha="left", fontfamily="monospace")
        plt.figtext(x, 0.920, label, fontsize=8, color=GREY, ha="left",
                    fontfamily="monospace", fontweight="bold", alpha=0.7)
        plt.figtext(x, 0.905, sub, fontsize=7, color=GREY, ha="left",
                    fontfamily="monospace", alpha=0.5)

    # ── trace with dual shading ──
    ax_trace = plt.subplot(2, 3, (1, 3))
    ax2 = ax_trace.twinx()
    ax_trace.plot(t, v, color=CYAN, linewidth=1.2, alpha=0.8, path_effects=GLOW)
    ax_trace.set_ylabel("Voltage (V)", color=CYAN)
    ax_trace.tick_params(axis="y", colors=CYAN)
    ax2.plot(t, ma, color=MAGENTA, linewidth=1.0, alpha=0.5)
    ax2.set_ylabel("Current (mA)", color=MAGENTA)
    ax2.tick_params(axis="y", colors=MAGENTA)
    for b in fast:
        ax_trace.axvspan(b["start_s"], b["end_s"], color=CYAN, alpha=0.08, lw=0)
    for b in slow:
        ax_trace.axvspan(b["start_s"], b["end_s"], color=MAGENTA, alpha=0.08, lw=0)
    ax_trace.set_xlabel("Time (s)")
    ax_trace.grid(True, alpha=0.2)

    # ── duration comparison table ──
    ax_tab = plt.subplot(2, 3, 4)
    ax_tab.axis("off")
    rows = [
        ("", lab_f.upper(), lab_s.upper()),
        ("Count", str(len(fast)), str(len(slow))),
        ("Min dur", f"{min(b['duration_s'] for b in fast)*1000:.0f} ms" if fast else "—",
                    f"{min(b['duration_s'] for b in slow)*1000:.0f} ms" if slow else "—"),
        ("Max dur", f"{max(b['duration_s'] for b in fast)*1000:.0f} ms" if fast else "—",
                    f"{max(b['duration_s'] for b in slow)*1000:.0f} ms" if slow else "—"),
        ("Avg dur", f"{np.mean([b['duration_s'] for b in fast])*1000:.0f} ms" if fast else "—",
                    f"{np.mean([b['duration_s'] for b in slow])*1000:.0f} ms" if slow else "—"),
        ("Avg I",   f"{np.mean([b['c_avg'] for b in fast]):.1f} mA" if fast else "—",
                    f"{np.mean([b['c_avg'] for b in slow]):.1f} mA" if slow else "—"),
        ("Peak I",  f"{max(b['c_max'] for b in fast):.0f} mA" if fast else "—",
                    f"{max(b['c_max'] for b in slow):.0f} mA" if slow else "—"),
        ("Min V",   f"{min(b['v_min'] for b in fast):.2f} V" if fast else "—",
                    f"{min(b['v_min'] for b in slow):.2f} V" if slow else "—"),
        ("Energy",  f"{np.mean([b['energy_mwh'] for b in fast])*3_600_000:.0f} µJ" if fast else "—",
                    f"{np.mean([b['energy_mwh'] for b in slow])*3_600_000:.0f} µJ" if slow else "—"),
        ("Battery", f"{batt_fast['normal']['years']:.1f} yr" if fast else "—",
                    f"{batt_slow['normal']['years']:.1f} yr" if slow else "—"),
    ]
    for j, row in enumerate(rows):
        for k, cell in enumerate(row):
            if j == 0:
                color, size, weight = CYAN if k == 1 else (MAGENTA if k == 2 else GREY), 11, "bold"
            elif k == 0:
                color, size, weight = GREY, 9, "normal"
            elif k == 1:
                color, size, weight = CYAN, 10, "bold"
            else:
                color, size, weight = MAGENTA, 10, "bold"
            ax_tab.text(0.05 + k * 0.45, 0.92 - j * 0.09, cell,
                        transform=ax_tab.transAxes, fontsize=size,
                        color=color, fontfamily="monospace", fontweight=weight)

    # ── duration histogram ──
    ax_dur = plt.subplot(2, 3, 5)
    d_fast = [b["duration_s"] * 1000 for b in fast]
    d_slow = [b["duration_s"] * 1000 for b in slow]
    all_d = d_fast + d_slow
    bins = np.linspace(0, max(all_d) * 1.15, 20)
    ax_dur.hist([d_fast, d_slow], bins=bins, color=[CYAN, MAGENTA], alpha=0.7,
                edgecolor="white", linewidth=0.5, label=[lab_f, lab_s])
    ax_dur.axvline(np.mean(d_fast) if d_fast else 0, color=CYAN, linewidth=1.5,
                   linestyle="--")
    ax_dur.axvline(np.mean(d_slow) if d_slow else 0, color=MAGENTA, linewidth=1.5,
                   linestyle="--")
    ax_dur.set_xlabel("Duration (ms)")
    ax_dur.set_ylabel("Count")
    ax_dur.legend(fontsize=8, facecolor=CARD, edgecolor=GRID)
    ax_dur.grid(True, alpha=0.2)

    # ── energy per burst scatter ──
    ax_en = plt.subplot(2, 3, 6)
    if fast:
        ax_en.scatter([b["duration_s"]*1000 for b in fast],
                      [b["energy_mwh"]*3_600_000 for b in fast],
                      c=CYAN, s=60, alpha=0.8, label=lab_f, edgecolors="white", linewidth=0.5)
    if slow:
        ax_en.scatter([b["duration_s"]*1000 for b in slow],
                      [b["energy_mwh"]*3_600_000 for b in slow],
                      c=MAGENTA, s=60, alpha=0.8, label=lab_s, edgecolors="white", linewidth=0.5)
    ax_en.set_xlabel("Duration (ms)")
    ax_en.set_ylabel("Energy (µJ)")
    ax_en.legend(fontsize=8, facecolor=CARD, edgecolor=GRID)
    ax_en.grid(True, alpha=0.2)

    plt.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(out_path, bbox_inches="tight")
    plt.close()
    print(f"  → {out_path}")


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Power Profiler — cyberpunk plotter")
    parser.add_argument("input", nargs="?", default="controle.txt",
                        help="CSV file from power profiler")
    parser.add_argument("-o", "--output", default="plot",
                        help="Output base name (without extension)")
    parser.add_argument("--compact", action="store_true",
                        help="Single combined chart instead of 3 separate")
    parser.add_argument("--analyze", action="store_true",
                        help="Burst detection + battery life estimation")
    parser.add_argument("--dual", action="store_true",
                        help="Dual burst analysis: auto-classify short vs long bursts")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="Current threshold for burst detection (mA, default 0.5)")
    args = parser.parse_args()

    t, v, ma, mw, energy, dt = load_csv(args.input)

    if args.analyze:
        bursts_raw, bursts = detect_bursts(t, v, ma, mw, dt, threshold=args.threshold)
        idle_ma = float(np.mean(ma[ma <= args.threshold])) if (ma <= args.threshold).any() else 0.0

        if args.dual and len(bursts) >= 4:
            fast, slow, labels = classify_bursts(bursts)
            if slow and labels[0]:
                lab_f, lab_s = labels
                s_fast = burst_stats(fast, t[-1] - t[0], idle_ma)
                s_slow = burst_stats(slow, t[-1] - t[0], idle_ma)
                b_fast = estimate_battery(s_fast, t[-1] - t[0])
                b_slow = estimate_battery(s_slow, t[-1] - t[0])

                print(f"\n  ⚡ DUAL BURST ANALYSIS  —  {lab_f} vs {lab_s}")
                print(f"  {'─' * 60}")
                for label, st, bt, color in [
                    (lab_f, s_fast, b_fast, CYAN),
                    (lab_s, s_slow, b_slow, MAGENTA)]:
                    print(f"  {label}:")
                    print(f"    Bursts: {st['n_bursts']:>4d}   "
                          f"Duration: {st['duration_s_avg']*1000:.0f} ms avg  "
                          f"({min(b['duration_s'] for b in (fast if label==lab_f else slow))*1000:.0f} – "
                          f"{max(b['duration_s'] for b in (fast if label==lab_f else slow))*1000:.0f} ms)")
                    print(f"    Current: {st['c_avg_avg']:.1f} mA avg  "
                          f"(peak {st['c_max_peak']:.0f} mA)  "
                          f"Voltage: {st['v_min_global']:.2f} V min")
                    print(f"    Energy:  {st['energy_uj_per']:.0f} µJ/burst  "
                          f"({st['energy_uj_total']:.0f} µJ total)")
                    print(f"    Battery: {bt['normal']['days']:.0f} days  "
                          f"({bt['normal']['years']:.1f} years  @ 4 presses/day)")
                    print()

                plot_dual_analysis(t, v, ma, mw, dt, fast, slow, labels,
                                   s_fast, b_fast, s_slow, b_slow,
                                   f"{args.output}_dual.png")
                # fall through to basic chart
            else:
                args.dual = False  # fallback to single analysis

        if not args.dual:
            stats = burst_stats(bursts, t[-1] - t[0], idle_ma)
            if stats is not None:
                batt = estimate_battery(stats, t[-1] - t[0])
            else:
                batt = {"avg_ma": 0, "usable_mah": 225, "total_mwh": 675,
                        "captured": {"days": float("inf"), "months": float("inf"), "years": float("inf")},
                        "normal": {"days": float("inf"), "months": float("inf"), "years": float("inf"),
                                   "presses_day": 4}}

            if stats:
                print(f"\n  ⚡ BURST ANALYSIS")
                print(f"  {'─' * 50}")
                print(f"  Bursts detected:  {stats['n_bursts']:>6d}   ({stats['bursts_per_min']:.1f}/min)")
                print(f"  Avg duration:     {stats['duration_s_avg']*1000:>6.0f} ms  (max {stats['duration_s_p95']*1000:.0f} ms p95)")
                print(f"  Avg active I:     {stats['c_avg_avg']:>6.1f} mA  (peak {stats['c_max_peak']:.1f} mA)")
                print(f"  Voltage sag:       {stats['v_min_global']:>6.2f} V  min under load")
                print(f"  Energy per burst: {stats['energy_uj_per']:>6.0f} µJ")
                print(f"  Total energy:     {stats['energy_uj_total']:>6.0f} µJ")
                print(f"  Duty cycle:       {stats['duty_pct']:>6.1f} %")
                print(f"")
                print(f"  🔋 BATTERY LIFE  (CR2032, {batt['usable_mah']:.0f} mAh usable)")

            if stats:
                print(f"  Average burst:     {stats['energy_uj_per']:.0f} µJ")
                print(f"  Average current:  {batt['avg_ma']:.2f} mA")
                print(f"")
                print(f"  Captured pattern  ({stats['duty_pct']:.1f}% duty, {stats['bursts_per_min']:.0f}/min):")
                print(f"    → {batt['captured']['days']:.0f}d  ({batt['captured']['months']:.1f} months)")
                print(f"")
                print(f"  Normal use  ({batt['normal']['presses_day']:.0f} presses/day):")
                print(f"    → {batt['normal']['days']:.0f} days  ({batt['normal']['months']:.1f} months, {batt['normal']['years']:.2f} years)")

            plot_analysis(t, v, ma, mw, dt, bursts, stats, batt,
                          f"{args.output}_analysis.png")

    if args.compact:
        plot_compact(t, v, ma, mw, energy, dt, f"{args.output}.png")
    else:
        plot_all(t, v, ma, mw, energy, f"{args.output}.png")


def plot_compact(t, v, ma, mw, energy, dt, out_path):
    fig, (ax, ax_e) = plt.subplots(2, 1, figsize=(16, 8),
                                    gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle("Power Profiler — Compact", fontsize=18,
                 fontweight="bold", y=0.98, color=CYAN)
    ax.plot(t, v, color=CYAN, linewidth=1.2, label="Voltage (V)")
    ax.plot(t, ma, color=MAGENTA, linewidth=1.2, label="Current (mA)")
    ax.plot(t, mw, color=YELLOW, linewidth=1.2, label="Power (mW)")
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


if __name__ == "__main__":
    main()
