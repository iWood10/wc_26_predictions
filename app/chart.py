"""Rendert den Punkteverlauf-Chart der Finale-Edition als PNG (für bot.send_photo)."""

import io

import matplotlib

matplotlib.use("Agg")  # headless – kein Display nötig
import matplotlib.pyplot as plt

# Validiertes kategorisches Palette-Slice (siehe dataviz-Skill), erste 5 Slots.
_COLORS = ["#2a78d6", "#008300", "#d55181", "#c98500", "#1baf7a"]

# Phasen-Grenzen in Spiel-IDs (1-basiert, inklusiv) für Achsenbeschriftung.
_PHASES = [("Vorrunde", 1, 72), ("16tel", 73, 88), ("8tel", 89, 96), ("Finalrunde", 97, 104)]


def render_progress_chart(cumulative: dict[str, list[int]]) -> bytes:
    """cumulative: Name -> kumulierte Gesamtpunkte nach Spiel 0..104 (Index 0 = Start).
    Zeichnet die Kurven relativ zum Schnitt aller Spieler (gemeinsame Steigung
    rausgerechnet, nur die relative Positionierung bleibt sichtbar)."""
    names = list(cumulative.keys())
    n = len(next(iter(cumulative.values()))) - 1  # i.d.R. 104
    columns = list(zip(*[cumulative[name] for name in names]))
    avg = [sum(col) / len(col) for col in columns]
    rel = {name: [v - a for v, a in zip(cumulative[name], avg)] for name in names}

    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")

    for i, name in enumerate(names):
        color = _COLORS[i % len(_COLORS)]
        series = rel[name]
        ax.plot(range(n + 1), series, color=color, linewidth=2.3, solid_capstyle="round", zorder=3)
        ax.annotate(
            f" {name}", xy=(n, series[-1]), xytext=(4, 0), textcoords="offset points",
            va="center", fontsize=10, fontweight="bold", color=color, annotation_clip=False,
        )

    ax.axhline(0, color="#9aa89f", linewidth=1.3, zorder=1)
    for _, start, _ in _PHASES[1:]:
        ax.axvline(start - 1, color="#e1e0d9", linewidth=0.9, zorder=0)

    ax.set_xlim(0, n + 9)
    ax.grid(axis="y", color="#e1e0d9", linewidth=0.8, zorder=0)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(axis="y", colors="#898781", labelsize=9)
    ax.tick_params(axis="x", length=0)

    ax.set_xticks([(start + end) / 2 for _, start, end in _PHASES])
    ax.set_xticklabels([label for label, _, _ in _PHASES], fontsize=10, color="#898781")

    ax.set_title(
        "Punkteverlauf — relativ zum Gruppenschnitt", fontsize=13, fontweight="bold",
        color="#0b0b0b", loc="left", pad=12,
    )

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
