"""Verknüpft Tipps + Ergebnisse + Scoring zu Leaderboard und History."""

from dataclasses import dataclass

from app.bets import Bet
from app.bracket import Bracket, build_bracket
from app.results import Results
from app.scoring import CHAMPION_POINTS, MatchScore, score_match
from app.tournament import Match

# Weiterkommen-Bonus: Runde -> (Match-IDs der Runde, Punkte je richtig
# vorhergesagtem Team). Sechzehntel zählt nicht (steht schon über die Gruppen fest),
# Spiel um Platz 3 (#103) auch nicht.
ADVANCE_ROUNDS: list[tuple[str, tuple[int, ...], int]] = [
    ("Achtelfinale", tuple(range(89, 97)), 1),
    ("Viertelfinale", tuple(range(97, 101)), 2),
    ("Halbfinale", (101, 102), 3),
    ("Finale", (104,), 5),
]


@dataclass
class HistoryRow:
    match_id: int
    team1: str
    team2: str
    prediction: str | None  # getipptes Ergebnis
    result: str             # echtes Ergebnis
    points: int
    categories: list[bool]  # die 5 Häkchen


@dataclass
class TipEntry:
    """Ein Spieler-Tipp für ein Spiel (für die kompakte Alle-Tipps-Ansicht)."""
    name: str
    prediction: str | None  # getipptes Ergebnis, None wenn nicht getippt
    points: int             # 0 solange das Spiel kein Ergebnis hat


def match_tips(
    bets: list[Bet], match_id: int, actual: str | None
) -> list[TipEntry]:
    """Alle Spieler-Tipps zu einem Spiel. points sind nur aussagekräftig,
    wenn das Spiel schon ein Ergebnis hat (sonst 0)."""
    entries = []
    for bet in bets:
        prediction = bet.prediction_for(match_id)
        points = score_match(prediction or "", actual).points if actual else 0
        entries.append(TipEntry(name=bet.name, prediction=prediction, points=points))
    return entries


def champion_points(bet: Bet, champion: str | None) -> int:
    """CHAMPION_POINTS Punkte, wenn der getippte Weltmeister stimmt."""
    if champion and bet.champion and bet.champion == champion:
        return CHAMPION_POINTS
    return 0


def total_points(
    bet: Bet, results: Results, champion: str | None, scorer=score_match
) -> int:
    """Gesamtpunktzahl eines Spielers: alle Spiele + Weltmeister-Bonus.
    scorer wählt die Wertung (score_match = Standard, score_match_alt = Alt)."""
    total = 0
    for match_id_str, actual in results.matches.items():
        prediction = bet.predictions.get(match_id_str)
        if prediction is not None:
            total += scorer(prediction, actual).points
    return total + champion_points(bet, champion)


@dataclass
class AdvanceRow:
    round_name: str
    per_team: int          # Punkte je richtig vorhergesagtem Team
    correct: list[str]     # korrekt vorhergesagte Teams dieser Runde
    points: int


def _round_teams(bracket: Bracket, match_ids: tuple[int, ...]) -> set[str]:
    """Aufgelöste Teams, die in den Spielen dieser Runde stehen (None fällt raus)."""
    teams: set[str] = set()
    for mid in match_ids:
        for team in bracket.teams_for(mid):
            if team:
                teams.add(team)
    return teams


def predicted_bracket(bet: Bet, results: Results, matches: list[Match]) -> Bracket:
    """Bracket des Spielers: echte Gruppenergebnisse (feste R32-Paarungen) + eigene
    K.o.-Tipps. Ein fehlender K.o.-Tipp lässt den Zweig 'abbrechen' (Sieger = None),
    sodass daraus keine Teams für spätere Runden vorhergesagt werden."""
    merged = {k: v for k, v in results.matches.items() if int(k) <= 72}
    merged.update({k: v for k, v in bet.predictions.items() if int(k) >= 73})
    return build_bracket(matches, Results(matches=merged))


def advancement_breakdown(
    bet: Bet, results: Results, matches: list[Match], actual: Bracket
) -> list[AdvanceRow]:
    """Weiterkommen-Bonus je Runde: Schnittmenge aus vorhergesagten und echten Teams."""
    pred = predicted_bracket(bet, results, matches)
    rows = []
    for name, ids, per in ADVANCE_ROUNDS:
        correct = sorted(_round_teams(pred, ids) & _round_teams(actual, ids))
        rows.append(AdvanceRow(name, per, correct, len(correct) * per))
    return rows


def advancement_points(
    bet: Bet, results: Results, matches: list[Match], actual: Bracket
) -> int:
    """Gesamter Weiterkommen-Bonus eines Spielers."""
    return sum(r.points for r in advancement_breakdown(bet, results, matches, actual))


def leaderboard(
    bets: list[Bet],
    results: Results,
    champion: str | None,
    matches: list[Match],
    scorer=score_match,
) -> list[tuple[Bet, int]]:
    """Spieler nach Punkten sortiert (höchste zuerst).
    Enthält Spiel-Tipps + Weltmeister-Bonus + Weiterkommen-Bonus."""
    actual = build_bracket(matches, results)
    ranked = [
        (
            bet,
            total_points(bet, results, champion, scorer)
            + advancement_points(bet, results, matches, actual),
        )
        for bet in bets
    ]
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return ranked


def history(
    bet: Bet,
    results: Results,
    matches: list[Match],
    limit: int | None = None,
    bracket: Bracket | None = None,
) -> list[HistoryRow]:
    """Tipp-Historie eines Spielers: nur bereits gespielte Spiele,
    neueste zuerst (höchste Spiel-ID zuerst). Mit bracket werden
    K.o.-Platzhalter zu echten Teamnamen aufgelöst."""
    by_id = {m.id: m for m in matches}
    rows: list[HistoryRow] = []

    for match_id_str, actual in results.matches.items():
        match_id = int(match_id_str)
        match = by_id.get(match_id)
        if match is None:
            continue
        prediction = bet.predictions.get(match_id_str)
        score: MatchScore = score_match(prediction or "", actual)

        team1, team2 = match.team1, match.team2
        if bracket is not None:
            r1, r2 = bracket.teams_for(match_id)
            team1, team2 = r1 or match.team1, r2 or match.team2

        rows.append(
            HistoryRow(
                match_id=match_id,
                team1=team1,
                team2=team2,
                prediction=prediction,
                result=actual,
                points=score.points,
                categories=score.categories,
            )
        )

    # neueste zuerst, chronologisch (Datum) – nicht nach FIFA-ID
    rows.sort(key=lambda r: (by_id[r.match_id].date, r.match_id), reverse=True)
    if limit is not None:
        rows = rows[:limit]
    return rows
