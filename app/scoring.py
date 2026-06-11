"""Bewertung eines Tipps gegen das tatsächliche Ergebnis.

Pro Spiel max. 5 Punkte:
  1. Richtiger Ausgang (Sieg/Unentschieden/Niederlage)
  2. Richtige Tordifferenz
  3. Tore Heim absolut richtig
  4. Tore Auswärts absolut richtig
  5. Bonus: wenn 1–4 alle stimmen (= exaktes Ergebnis)

Für den richtigen Weltmeister gibt es zusätzlich CHAMPION_POINTS.
"""

from dataclasses import dataclass

CHAMPION_POINTS = 50

# Reihenfolge der Kategorie-Häkchen (für die History-Anzeige)
CATEGORY_NAMES = ["ausgang", "tordifferenz", "tore_heim", "tore_auswaerts", "bonus"]


def parse_score(text: str) -> tuple[int, int] | None:
    """Wandelt "2:1" in (2, 1) um. Gibt None bei ungültigem/leerem Text."""
    if not text:
        return None
    text = text.strip().replace("-", ":")
    if ":" not in text:
        return None
    home, _, away = text.partition(":")
    try:
        return int(home.strip()), int(away.strip())
    except ValueError:
        return None


def _outcome(home: int, away: int) -> int:
    """+1 Heimsieg, 0 Unentschieden, -1 Auswärtssieg (Vorzeichen des Ergebnisses)."""
    return (home > away) - (home < away)


@dataclass
class MatchScore:
    points: int
    categories: list[bool]  # [ausgang, tordiff, tore_heim, tore_auswaerts, bonus]


def score_match(prediction: str, actual: str) -> MatchScore:
    """Bewertet einen Tipp gegen das echte Ergebnis (beide als "2:1")."""
    pred = parse_score(prediction)
    real = parse_score(actual)

    # Ohne gültigen Tipp oder ohne Ergebnis: 0 Punkte, alles falsch.
    if pred is None or real is None:
        return MatchScore(points=0, categories=[False] * 5)

    ph, pa = pred
    rh, ra = real

    ausgang = _outcome(ph, pa) == _outcome(rh, ra)
    tordiff = (ph - pa) == (rh - ra)
    tore_heim = ph == rh
    tore_auswaerts = pa == ra
    bonus = ausgang and tordiff and tore_heim and tore_auswaerts

    cats = [ausgang, tordiff, tore_heim, tore_auswaerts, bonus]
    return MatchScore(points=sum(cats), categories=cats)
