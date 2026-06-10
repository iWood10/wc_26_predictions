"""Berechnet die Gruppentabellen aus den eingetragenen Ergebnissen.

Sortierung nach FIFA-Kriterien:
  1. Punkte
  2. Tordifferenz (alle Spiele)
  3. erzielte Tore (alle Spiele)
  4. direkter Vergleich (Punkte, Tordiff, Tore nur unter den Punktgleichen)
  5. alphabetisch (deterministischer Notnagel statt Fair-Play/Losentscheid)
"""

from dataclasses import dataclass

from app.results import Results
from app.scoring import parse_score
from app.tournament import Match


@dataclass
class Standing:
    team: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def points(self) -> int:
        return self.won * 3 + self.drawn

    @property
    def goal_diff(self) -> int:
        return self.goals_for - self.goals_against


def _apply(table: dict[str, Standing], home: str, away: str, hg: int, ag: int) -> None:
    """Verbucht ein Spielergebnis in der Tabelle."""
    h = table.setdefault(home, Standing(team=home))
    a = table.setdefault(away, Standing(team=away))
    h.played += 1
    a.played += 1
    h.goals_for += hg
    h.goals_against += ag
    a.goals_for += ag
    a.goals_against += hg
    if hg > ag:
        h.won += 1
        a.lost += 1
    elif hg < ag:
        a.won += 1
        h.lost += 1
    else:
        h.drawn += 1
        a.drawn += 1


def _head_to_head(teams: list[str], group_matches: list[tuple[str, str, int, int]]) -> dict[str, Standing]:
    """Mini-Tabelle nur aus den Spielen zwischen den genannten Teams."""
    names = set(teams)
    table: dict[str, Standing] = {t: Standing(team=t) for t in teams}
    for home, away, hg, ag in group_matches:
        if home in names and away in names:
            _apply(table, home, away, hg, ag)
    return table


def compute_group_tables(
    matches: list[Match], results: Results
) -> dict[str, list[Standing]]:
    """Gibt pro Gruppe ("A".."L") die sortierte Standing-Liste zurück."""
    # Gespielte Gruppenspiele je Gruppe sammeln: (heim, auswärts, hg, ag)
    played: dict[str, list[tuple[str, str, int, int]]] = {}
    for m in matches:
        if m.group is None:
            continue
        result = results.result_for(m.id)
        score = parse_score(result) if result else None
        if score is None:
            continue
        letter = m.group.replace("Group ", "")
        played.setdefault(letter, []).append((m.team1, m.team2, score[0], score[1]))

    tables: dict[str, list[Standing]] = {}
    for letter, group_matches in played.items():
        table: dict[str, Standing] = {}
        for home, away, hg, ag in group_matches:
            _apply(table, home, away, hg, ag)
        tables[letter] = _sort_group(list(table.values()), group_matches)
    return tables


def _sort_group(
    standings: list[Standing], group_matches: list[tuple[str, str, int, int]]
) -> list[Standing]:
    """Sortiert eine Gruppe nach den FIFA-Kriterien (siehe Modul-Docstring)."""

    def primary_key(s: Standing) -> tuple[int, int, int]:
        return (s.points, s.goal_diff, s.goals_for)

    # 1. Vorsortierung nach Punkte / Tordiff / Tore
    standings.sort(key=primary_key, reverse=True)

    # 2. Punktgleiche Blöcke per direktem Vergleich auflösen
    result: list[Standing] = []
    i = 0
    while i < len(standings):
        j = i
        while j < len(standings) and primary_key(standings[j]) == primary_key(standings[i]):
            j += 1
        block = standings[i:j]
        if len(block) > 1:
            h2h = _head_to_head([s.team for s in block], group_matches)
            # negierte Zahlen → absteigend, Team aufsteigend (alphabetisch korrekt)
            block.sort(
                key=lambda s: (
                    -h2h[s.team].points,
                    -h2h[s.team].goal_diff,
                    -h2h[s.team].goals_for,
                    s.team,  # alphabetischer Notnagel
                )
            )
        result.extend(block)
        i = j
    return result
