"""Lädt die WM-26-Turnierdaten (Spielplan + Gruppen) aus data/tournament.json.

Quelle der Daten: openfootball/worldcup.json (Public Domain).
Jedes Spiel bekommt hier eine stabile ID 1–104 in Spielplan-Reihenfolge
(entspricht der offiziellen FIFA-Nummerierung: Gruppe 1–72, K.o. 73–104).
"""

import json
from dataclasses import dataclass
from pathlib import Path

# Pfad zur lokalen Turnierdatei (eine Ebene über app/, im data/-Ordner)
DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "tournament.json"


@dataclass
class Match:
    """Ein einzelnes Spiel im Turnier."""

    id: int            # stabile ID 1–104
    round: str         # z.B. "Matchday 1", "Round of 32", "Final"
    date: str          # "2026-06-11"
    team1: str         # Heim — echtes Team oder Platzhalter ("2A", "W101")
    team2: str         # Auswärts
    group: str | None  # "Group A" … "Group L"; None bei K.o.-Spielen
    ground: str        # Austragungsort

    @property
    def is_knockout(self) -> bool:
        """K.o.-Spiel? (Gruppenspiele haben eine Gruppe, K.o.-Spiele nicht.)"""
        return self.group is None


def load_matches(path: Path = DATA_FILE) -> list[Match]:
    """Liest alle 104 Spiele aus der JSON-Datei und vergibt IDs 1–104."""
    data = json.loads(path.read_text(encoding="utf-8"))
    matches = []
    for index, m in enumerate(data["matches"], start=1):
        matches.append(
            Match(
                id=index,
                round=m["round"],
                date=m.get("date", ""),
                team1=m["team1"],
                team2=m["team2"],
                group=m.get("group"),
                ground=m.get("ground", ""),
            )
        )
    return matches


if __name__ == "__main__":
    # Kleiner Selbsttest: zeigt, dass der Lader funktioniert.
    matches = load_matches()
    print(f"Geladen: {len(matches)} Spiele")
    print(f"Erstes:  #{matches[0].id} {matches[0].team1} vs {matches[0].team2} ({matches[0].group})")
    print(f"Letztes: #{matches[-1].id} {matches[-1].team1} vs {matches[-1].team2} ({matches[-1].round})")
