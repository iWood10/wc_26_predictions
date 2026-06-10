"""Lädt und speichert die tatsächlichen Spielergebnisse in data/results.json.

Format:
    {
        "champion": "Brazil",
        "matches": { "1": "2:1", "2": "0:0" },
        "manual":  ["1"]
    }
matches: Spiel-ID (als String) -> echtes Ergebnis "heim:auswaerts".
manual:  IDs, die per /result von Hand gesetzt wurden. Diese werden vom
         Auto-Sync (openfootball) NICHT überschrieben.
champion: wird nicht mehr benutzt (Weltmeister wird aus #104 abgeleitet).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

RESULTS_FILE = Path(__file__).resolve().parent.parent / "data" / "results.json"


@dataclass
class Results:
    champion: str | None = None
    matches: dict[str, str] = field(default_factory=dict)
    manual: set[str] = field(default_factory=set)

    def result_for(self, match_id: int) -> str | None:
        """Echtes Ergebnis eines Spiels, oder None wenn noch nicht eingetragen."""
        return self.matches.get(str(match_id))


def load_results(path: Path = RESULTS_FILE) -> Results:
    """Liest die Ergebnisdatei; gibt leere Results zurück, wenn sie fehlt."""
    if not path.exists():
        return Results()
    data = json.loads(path.read_text(encoding="utf-8"))
    return Results(
        champion=data.get("champion"),
        matches=data.get("matches", {}),
        manual=set(data.get("manual", [])),
    )


def save_results(results: Results, path: Path = RESULTS_FILE) -> None:
    """Schreibt die Ergebnisse zurück auf die Platte (hübsch formatiert)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "champion": results.champion,
        "matches": results.matches,
        "manual": sorted(results.manual, key=int),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def set_match_result(match_id: int, score: str, path: Path = RESULTS_FILE) -> Results:
    """Trägt ein Ergebnis von Hand ein (markiert es als 'manual') und speichert."""
    results = load_results(path)
    results.matches[str(match_id)] = score
    results.manual.add(str(match_id))
    save_results(results, path)
    return results
