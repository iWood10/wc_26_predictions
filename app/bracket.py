"""Löst die K.o.-Platzhalter zu echten Teams auf.

Platzhalter-Formen:
  "1E", "2C"        Gruppensieger / -zweiter  -> aus den Gruppentabellen
  "3A/B/C/D/F"      Slot für einen Gruppendritten -> über data/thirds.json
  "W74"             Sieger von Spiel 74        -> rekursiv (höhere Tore)
  "L101"            Verlierer von Spiel 101    -> rekursiv
  sonst             echtes Team (Gruppenphase) -> unverändert

Unauflösbare Platzhalter (Spiel noch nicht gespielt, Mapping fehlt) bleiben None.
"""

import json
import re
from pathlib import Path

from app.groups import compute_group_tables
from app.results import Results
from app.scoring import parse_score
from app.tournament import Match

THIRDS_FILE = Path(__file__).resolve().parent.parent / "data" / "thirds.json"

_GROUP_POS = re.compile(r"^([12])([A-L])$")
_WINNER = re.compile(r"^W(\d+)$")
_LOSER = re.compile(r"^L(\d+)$")


def load_thirds(path: Path = THIRDS_FILE) -> dict[str, str]:
    """Mapping Dritten-Slot -> Gruppenbuchstabe, z.B. {"3A/B/C/D/F": "C"}."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


class Bracket:
    """Löst Platzhalter auf Basis von Ergebnissen + Gruppentabellen + Dritten-Mapping."""

    def __init__(self, matches: list[Match], results: Results, thirds: dict[str, str]):
        self.by_id = {m.id: m for m in matches}
        self.results = results
        self.thirds = thirds
        self.tables = compute_group_tables(matches, results)
        self._cache: dict[str, str | None] = {}

    def _from_table(self, letter: str, index: int) -> str | None:
        table = self.tables.get(letter, [])
        if len(table) > index:
            return table[index].team
        return None

    def resolve_token(self, token: str) -> str | None:
        """Wandelt einen Platzhalter (oder echten Namen) in einen Teamnamen um."""
        if token in self._cache:
            return self._cache[token]
        result = self._resolve_token_uncached(token)
        self._cache[token] = result
        return result

    def _resolve_token_uncached(self, token: str) -> str | None:
        m = _GROUP_POS.match(token)
        if m:
            return self._from_table(m.group(2), int(m.group(1)) - 1)

        if token.startswith("3") and "/" in token:
            letter = self.thirds.get(token)
            return self._from_table(letter, 2) if letter else None

        m = _WINNER.match(token)
        if m:
            return self._winner_loser(int(m.group(1)), want_winner=True)

        m = _LOSER.match(token)
        if m:
            return self._winner_loser(int(m.group(1)), want_winner=False)

        return token  # echtes Team

    def _winner_loser(self, match_id: int, want_winner: bool) -> str | None:
        match = self.by_id.get(match_id)
        if match is None:
            return None
        score = parse_score(self.results.result_for(match_id) or "")
        if score is None:
            return None  # Spiel noch nicht gespielt
        team1 = self.resolve_token(match.team1)
        team2 = self.resolve_token(match.team2)
        home_won = score[0] > score[1]
        if want_winner:
            return team1 if home_won else team2
        return team2 if home_won else team1

    def teams_for(self, match_id: int) -> tuple[str | None, str | None]:
        """Aufgelöste (team1, team2) eines Spiels (None falls noch offen)."""
        match = self.by_id[match_id]
        return self.resolve_token(match.team1), self.resolve_token(match.team2)

    def champion(self) -> str | None:
        """Weltmeister = Sieger des Finales (Spiel #104)."""
        return self._winner_loser(104, want_winner=True)


def build_bracket(
    matches: list[Match], results: Results, thirds: dict[str, str] | None = None
) -> Bracket:
    return Bracket(matches, results, thirds if thirds is not None else load_thirds())
