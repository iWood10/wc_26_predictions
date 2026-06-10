"""Lädt die Wett-Zettel der Spieler aus data/bets/<name>.bet.

Eigene Endung .bet – der Inhalt ist aber ganz normales JSON:
    {
        "name": "mori",
        "champion": "Brazil",
        "predictions": {
            "1": "2:1",
            "2": "0:0"
        }
    }
predictions: Spiel-ID (als String) -> getipptes Ergebnis "heim:auswaerts".
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

BETS_DIR = Path(__file__).resolve().parent.parent / "data" / "bets"
BET_EXT = ".bet"  # kanonische Endung der Tipp-Dateien


@dataclass
class Bet:
    name: str
    champion: str | None = None
    predictions: dict[str, str] = field(default_factory=dict)

    def prediction_for(self, match_id: int) -> str | None:
        """Getippter Spielstand für ein Spiel, oder None wenn nicht getippt."""
        return self.predictions.get(str(match_id))


def load_bets(bets_dir: Path = BETS_DIR) -> list[Bet]:
    """Liest alle Wett-Dateien (*.bet) aus dem bets/-Ordner."""
    bets = []
    for path in sorted(bets_dir.glob(f"*{BET_EXT}")):
        data = json.loads(path.read_text(encoding="utf-8"))
        bets.append(
            Bet(
                name=data.get("name", path.stem),
                champion=data.get("champion"),
                predictions=data.get("predictions", {}),
            )
        )
    return bets
