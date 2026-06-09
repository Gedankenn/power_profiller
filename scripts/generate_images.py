#!/usr/bin/env python3
"""Generate schematic images for the power profiler README."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

OUT_DIR = "docs"
DPI = 150


def draw_wiring_diagram():
    """Physical wiring diagram: ESP32 + INA226 + divider + load."""
    fig, ax = plt.subplots(1, 1, figsize=(14, 8))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 8)
    ax.set_aspect("equal")
    ax.axis("off")

    # Colors
    C_ESP = "#1a1a2e"
    C_INA = "#16213e"
    C_LOAD = "#0f3460"
    C_WIRE = "#555"
    C_VBUS = "#e94560"
    C_GND = "#333"
    C_DIV = "#533483"
    C_TEXT = "#222"
    C_BG = "#fafafa"

    fig.patch.set_facecolor(C_BG)

    def box(ax, x, y, w, h, label, color, text_color="white", fontsize=11):
        """Draw a rounded box with label."""
        rect = FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.1",
            facecolor=color, edgecolor="#444", linewidth=1.5, zorder=2
        )
        ax.add_patch(rect)
        ax.text(x + w/2, y + h/2, label, ha="center", va="center",
                color=text_color, fontsize=fontsize, fontweight="bold", zorder=3)

    def pin(ax, x, y, label, side="right", color="#555", fontsize=8):
        """Draw a pin dot and label."""
        dx = 0.2 if side == "right" else -0.2
        ha = "left" if side == "right" else "right"
        ax.plot(x, y, "o", color=color, markersize=5, zorder=4)
        ax.text(x + dx, y, label, va="center", ha=ha, fontsize=fontsize,
                color=C_TEXT, fontfamily="monospace", zorder=4)

    def wire(ax, x1, y1, x2, y2, color=C_WIRE, lw=1.8, style="-"):
        ax.plot([x1, x2], [y1, y2], color=color, lw=lw, linestyle=style, zorder=1)

    def color_wire(ax, points, color, lw=2.2):
        xs, ys = zip(*points)
        ax.plot(xs, ys, color=color, lw=lw, zorder=1)

    # ---- ESP32 ----
    box(ax, 0.5, 2.5, 3.0, 3.5, "ESP32\nDev Board", C_ESP, "white", 12)
    pin(ax, 3.5, 5.5, "GPIO21 (SDA)", "right", "#f0a500")
    pin(ax, 3.5, 4.8, "GPIO22 (SCL)", "right", "#f0a500")
    pin(ax, 3.5, 4.1, "GPIO34 (ADC)", "right", "#00b4d8")
    pin(ax, 3.5, 3.4, "GND", "right", "#555")
    pin(ax, 1.5, 3.0, "USB-UART", "left", "#666", 7)

    # ---- INA226 ----
    box(ax, 6.5, 4.0, 3.0, 3.0, "INA226\nModule", C_INA, "white", 12)
    pin(ax, 6.5, 6.3, "SDA", "left", "orange")
    pin(ax, 6.5, 5.6, "SCL", "left", "orange")
    pin(ax, 9.5, 6.3, "VBUS", "right", C_VBUS)
    pin(ax, 9.5, 5.6, "VIN+", "right", "orange")
    pin(ax, 9.5, 4.9, "VIN-", "right", "orange")
    pin(ax, 9.5, 4.2, "GND", "right", "#555")

    # ---- Shunt resistor ----
    ax.plot([10.8, 11.6], [5.6, 5.6], color=C_VBUS, lw=3, zorder=3)
    ax.text(11.2, 5.85, "0.1 Ω", ha="center", fontsize=8, color=C_TEXT, fontweight="bold")
    ax.text(11.2, 6.0, "shunt", ha="center", fontsize=7, color="#666")

    # ---- Load ----
    box(ax, 11.5, 4.0, 2.0, 3.0, "LOAD\n(device\nunder\n test)", C_LOAD, "white", 10)
    pin(ax, 11.5, 6.3, "V+", "left", C_VBUS)
    pin(ax, 11.5, 4.2, "GND", "left", "#555")

    # ---- Voltage Divider ----
    box(ax, 4.5, 0.8, 2.8, 1.6, "", "#e8dff5", "#333", 0)
    ax.text(5.9, 2.0, "Voltage\nDivider", ha="center", va="center",
            fontsize=10, color=C_DIV, fontweight="bold")
    ax.plot([5.1, 5.9], [1.6, 1.6], color=C_DIV, lw=2, zorder=3)
    ax.plot([5.9, 6.7], [1.6, 1.6], color=C_DIV, lw=2, zorder=3)
    ax.text(5.5, 1.35, "10kΩ", ha="center", fontsize=7, color=C_DIV)
    ax.text(6.3, 1.35, "10kΩ", ha="center", fontsize=7, color=C_DIV)
    ax.plot([5.9, 5.9], [1.6, 1.0], color="#777", lw=1.5, zorder=3)
    ax.text(5.9, 0.75, "GND", ha="center", fontsize=7, color="#666")

    # ---- WIRES ----

    # I2C: ESP32 SDA → INA226 SDA
    wire(ax, 3.5, 5.5, 6.5, 6.3, "#f0a500")
    # I2C: ESP32 SCL → INA226 SCL
    wire(ax, 3.5, 4.8, 6.5, 5.6, "#f0a500")

    # ADC: ESP32 GPIO34 → divider tap
    color_wire(ax, [(3.5, 4.1), (4.2, 4.1), (4.2, 1.6), (5.9, 1.6)], "#00b4d8")
    ax.plot(5.9, 1.6, "o", color="#00b4d8", markersize=8, zorder=5, markeredgecolor="white", markeredgewidth=1)

    # Load V+ → INA226 VIN+ (through shunt)
    color_wire(ax, [(11.5, 6.3), (10.8, 6.3), (10.8, 5.6), (9.5, 5.6)], C_VBUS)

    # INA226 VBUS → Load V+ (measure bus voltage at load)
    color_wire(ax, [(9.5, 6.3), (10.4, 6.3), (10.4, 6.5), (11.5, 6.5)], C_VBUS, 1.8)

    # Load V+ → divider top
    color_wire(ax, [(11.5, 6.3), (12.2, 6.3), (12.2, 2.0), (5.1, 2.0), (5.1, 1.6)], C_VBUS)
    ax.plot(5.1, 1.6, "o", color=C_VBUS, markersize=8, zorder=5, markeredgecolor="white", markeredgewidth=1)

    # Grounds
    wire(ax, 3.5, 3.4, 6.0, 3.4, "#888", 1.5, "--")
    wire(ax, 6.0, 3.4, 6.0, 4.2, "#888", 1.5, "--")
    wire(ax, 6.0, 4.2, 9.5, 4.2, "#888", 1.5, "--")
    wire(ax, 6.0, 3.4, 9.0, 3.4, "#888", 1.5, "--")
    wire(ax, 9.0, 3.4, 9.0, 1.0, "#888", 1.5, "--")
    wire(ax, 9.0, 1.0, 5.9, 1.0, "#888", 1.5, "--")
    wire(ax, 11.5, 4.2, 13.5, 4.2, "#888", 1.5, "--")
    # GND bus
    wire(ax, 3.5, 3.4, 13.7, 3.4, "#888", 1.0, "--")
    ax.text(13.9, 3.4, "GND", fontsize=7, color="#888", va="center")

    # Title
    ax.text(7.0, 7.5, "Power Profiler — Wiring Diagram", ha="center", fontsize=16,
            fontweight="bold", color=C_TEXT)

    # Legend / notes
    notes = [
        ("GPIO21/22 → I2C bus to INA226", "#f0a500"),
        ("GPIO34 → ADC reads divider tap", "#00b4d8"),
        ("Voltage divider: 0–5 V scaled to 0–2.5 V", C_DIV),
        ("Shunt resistor: 0.1 Ω (up to ~800 mA)", C_VBUS),
    ]
    for i, (text, color) in enumerate(notes):
        ax.plot(0.5, 0.35 - i*0.22, "s", color=color, markersize=8, clip_on=False)
        ax.text(0.8, 0.35 - i*0.22, text, fontsize=8, color="#555", va="center")

    plt.tight_layout(pad=0.5)
    fig.savefig(f"{OUT_DIR}/wiring-diagram.png", dpi=DPI, bbox_inches="tight",
                facecolor=C_BG, edgecolor="none")
    plt.close()
    print(f"  → {OUT_DIR}/wiring-diagram.png")


def draw_block_diagram():
    """High-level block diagram showing signal flow."""
    fig, ax = plt.subplots(1, 1, figsize=(12, 5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 5)
    ax.set_aspect("equal")
    ax.axis("off")

    C_BG = "#fafafa"
    fig.patch.set_facecolor(C_BG)

    colors = ["#e63946", "#457b9d", "#2a9d8f", "#e76f51", "#264653"]
    labels = [
        "INA226\n(current sensor)",
        "Voltage\nDivider",
        "ESP32\nADC + I2C",
        "Serial CSV\n(UART)",
        "Plot Script\n(PC)"
    ]
    boxes = [
        (0.3, 1.8, 2.2, 1.8),
        (0.3, 0.3, 2.2, 1.2),
        (3.5, 1.0, 2.2, 2.5),
        (6.8, 1.0, 2.2, 2.5),
        (10.0, 1.0, 1.8, 2.5),
    ]

    for (x, y, w, h), color, label in zip(boxes, colors, labels):
        rect = FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.15",
            facecolor=color, edgecolor="#333", linewidth=2
        )
        ax.add_patch(rect)
        ax.text(x + w/2, y + h/2, label, ha="center", va="center",
                color="white", fontsize=10, fontweight="bold")

    # Arrows between blocks
    arrow_style = dict(arrowstyle="->", color="#555", lw=2.5, mutation_scale=20)
    arrows = [
        (2.5, 2.7, 3.5, 2.7),      # INA226 → ESP32
        (2.5, 0.9, 3.5, 0.9),      # Divider → ESP32
        (5.7, 2.25, 6.8, 2.25),    # ESP32 → Serial
        (9.0, 2.25, 10.0, 2.25),   # Serial → PC
    ]
    for x1, y1, x2, y2 in arrows:
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=arrow_style, zorder=3)

    # Labels on arrows
    ax.text(3.0, 2.95, "I²C", ha="center", fontsize=8, color="#457b9d", fontweight="bold")
    ax.text(3.0, 0.65, "analog\n(ADC)", ha="center", fontsize=8, color="#2a9d8f", fontweight="bold")
    ax.text(6.25, 2.55, "CSV", ha="center", fontsize=8, color="#555", fontweight="bold")
    ax.text(9.5, 2.55, "USB", ha="center", fontsize=8, color="#555", fontweight="bold")

    # Title
    ax.text(6.0, 4.5, "Power Profiler — Block Diagram", ha="center", fontsize=16,
            fontweight="bold", color="#222")

    plt.tight_layout(pad=0.5)
    fig.savefig(f"{OUT_DIR}/block-diagram.png", dpi=DPI, bbox_inches="tight",
                facecolor=C_BG, edgecolor="none")
    plt.close()
    print(f"  → {OUT_DIR}/block-diagram.png")


if __name__ == "__main__":
    print("Generating images...")
    draw_wiring_diagram()
    draw_block_diagram()
    print("Done.")
