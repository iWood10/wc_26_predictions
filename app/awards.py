"""Auswertungen für die Finale-Edition: 10 Award-Kategorien + Zusatz-Kennzahlen.

Reine Berechnungsfunktionen (kein I/O) – arbeiten auf bereits geladenen
Bet-/Results-/Match-Objekten und sind so leicht mit synthetischen Daten
testbar. bot.py übernimmt die Formatierung als Telegram-Text.
"""

from collections import Counter
from dataclasses import dataclass

from app.bets import Bet
from app.bracket import build_bracket
from app.results import Results
from app.scoring import CHAMPION_POINTS, _outcome, parse_score, score_match
from app.standings import ADVANCE_ROUNDS, _round_teams, leaderboard, predicted_bracket
from app.tournament import Match


def _played_matches(results: Results, matches: list[Match]) -> list[Match]:
    """Nur Spiele mit eingetragenem Ergebnis, in Spiel-ID-Reihenfolge."""
    return [m for m in matches if results.result_for(m.id) is not None]


def _total_goals(score: str | None) -> int | None:
    parsed = parse_score(score) if score else None
    return sum(parsed) if parsed else None


# 1. Meiste exakte Tipps -------------------------------------------------

def exact_hits(bet: Bet, results: Results, matches: list[Match]) -> int:
    """Anzahl exakt getroffener Ergebnisse (Bonus-Kategorie in score_match)."""
    count = 0
    for m in _played_matches(results, matches):
        pred = bet.prediction_for(m.id)
        if pred is None:
            continue
        if score_match(pred, results.result_for(m.id)).categories[4]:
            count += 1
    return count


# 2. Mutigster Tipper ------------------------------------------------------

def boldness_score(bet: Bet, bets: list[Bet]) -> float | None:
    """Ø-Abweichung der eigenen getippten Gesamttorzahl vom Schnitt aller Tipps
    dieses Spiels, gemittelt über alle vom Spieler getippten Spiele
    (mit mind. 2 Tippern insgesamt). None, wenn keine auswertbaren Spiele."""
    deviations = []
    for match_id_str, own_score in bet.predictions.items():
        own_total = _total_goals(own_score)
        if own_total is None:
            continue
        totals = [
            t for t in (_total_goals(b.predictions.get(match_id_str)) for b in bets)
            if t is not None
        ]
        if len(totals) < 2:
            continue
        avg = sum(totals) / len(totals)
        deviations.append(abs(own_total - avg))
    if not deviations:
        return None
    return sum(deviations) / len(deviations)


# 3. Exotischster Treffer ---------------------------------------------------

@dataclass
class ExoticHit:
    name: str
    match_id: int
    score: str
    others_correct: int  # wie viele andere Spieler diesen Tipp auch exakt hatten


def exotic_hit(bets: list[Bet], results: Results, matches: list[Match]) -> ExoticHit | None:
    """Exakter Treffer, den am wenigsten andere auch hatten (Tie-Break: meiste Tore)."""
    candidates: list[ExoticHit] = []
    for m in _played_matches(results, matches):
        actual = results.result_for(m.id)
        hitters = [
            b.name for b in bets
            if (pred := b.prediction_for(m.id)) and score_match(pred, actual).categories[4]
        ]
        if not hitters:
            continue
        others = len(hitters) - 1
        for name in hitters:
            candidates.append(ExoticHit(name=name, match_id=m.id, score=actual, others_correct=others))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c.others_correct, -(_total_goals(c.score) or 0)))
    return candidates[0]


# 4. Schlechtester Tipp ------------------------------------------------------

@dataclass
class WorstTip:
    name: str
    match_id: int
    prediction: str
    actual: str
    distance: int  # |Δheim| + |Δauswärts|


def worst_single_tip(bets: list[Bet], results: Results, matches: list[Match]) -> WorstTip | None:
    """Der einzelne Tipp mit der größten Abweichung vom echten Ergebnis."""
    worst: WorstTip | None = None
    for m in _played_matches(results, matches):
        actual = results.result_for(m.id)
        rh, ra = parse_score(actual)
        for bet in bets:
            pred = bet.prediction_for(m.id)
            parsed = parse_score(pred) if pred else None
            if parsed is None:
                continue
            distance = abs(parsed[0] - rh) + abs(parsed[1] - ra)
            if worst is None or distance > worst.distance:
                worst = WorstTip(bet.name, m.id, pred, actual, distance)
    return worst


# 5. Orakel der K.o.-Runde ----------------------------------------------------

def ko_points(bet: Bet, results: Results, matches: list[Match]) -> int:
    """Spielpunkte (Standard-Wertung) nur aus den K.o.-Spielen (#73–104)."""
    total = 0
    for m in _played_matches(results, matches):
        if m.id < 73:
            continue
        pred = bet.prediction_for(m.id)
        if pred is None:
            continue
        total += score_match(pred, results.result_for(m.id)).points
    return total


# 6. Remis-König --------------------------------------------------------------

def draw_king(bet: Bet, results: Results, matches: list[Match]) -> int:
    """Anzahl exakt getroffener Unentschieden."""
    count = 0
    for m in _played_matches(results, matches):
        actual = results.result_for(m.id)
        rh, ra = parse_score(actual)
        if rh != ra:
            continue
        pred = bet.prediction_for(m.id)
        if pred and score_match(pred, actual).categories[4]:
            count += 1
    return count


# 7. Underdog-Riecher -----------------------------------------------------

def _majority_outcome(bets: list[Bet], match_id: int) -> int | None:
    """Häufigster getippter Ausgang für ein Spiel; None ohne klare Mehrheit."""
    outcomes = []
    for b in bets:
        pred = b.prediction_for(match_id)
        parsed = parse_score(pred) if pred else None
        if parsed:
            outcomes.append(_outcome(*parsed))
    if not outcomes:
        return None
    top = Counter(outcomes).most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return None  # kein klarer Favorit
    return top[0][0]


def underdog_score(bet: Bet, bets: list[Bet], results: Results, matches: list[Match]) -> int:
    """Richtige Tipps, die gegen den Mehrheits-Tipp der Gruppe gingen."""
    count = 0
    for m in _played_matches(results, matches):
        actual = results.result_for(m.id)
        actual_outcome = _outcome(*parse_score(actual))
        pred = bet.prediction_for(m.id)
        parsed = parse_score(pred) if pred else None
        if parsed is None:
            continue
        own_outcome = _outcome(*parsed)
        if own_outcome != actual_outcome:
            continue
        majority = _majority_outcome(bets, m.id)
        if majority is None or majority == actual_outcome or own_outcome == majority:
            continue
        count += 1
    return count


# 8. Aufholjagd / Absturz ------------------------------------------------------

def rank_swing(
    bets: list[Bet], results: Results, matches: list[Match], checkpoint: int = 72
) -> dict[str, int]:
    """Rang-Änderung vom Stand nach Spiel <checkpoint> (i.d.R. Gruppenphasen-Ende)
    bis zum Endstand. Positiv = aufgestiegen, negativ = abgestürzt."""
    early_results = Results(matches={k: v for k, v in results.matches.items() if int(k) <= checkpoint})
    early_ranked = leaderboard(bets, early_results, None, matches)
    champion = build_bracket(matches, results).champion()
    final_ranked = leaderboard(bets, results, champion, matches)

    early_rank = {bet.name: i for i, (bet, _) in enumerate(early_ranked, start=1)}
    final_rank = {bet.name: i for i, (bet, _) in enumerate(final_ranked, start=1)}
    return {name: early_rank[name] - final_rank[name] for name in early_rank}


# 9. Der Genaue ------------------------------------------------------------

def precision_score(bet: Bet, results: Results, matches: list[Match]) -> float | None:
    """Ø Tordifferenz-Summe (|Δheim| + |Δauswärts|) über alle getippten,
    gespielten Spiele. Niedriger = genauer. None ohne auswertbare Spiele."""
    distances = []
    for m in _played_matches(results, matches):
        pred = bet.prediction_for(m.id)
        parsed = parse_score(pred) if pred else None
        if parsed is None:
            continue
        rh, ra = parse_score(results.result_for(m.id))
        distances.append(abs(parsed[0] - rh) + abs(parsed[1] - ra))
    if not distances:
        return None
    return sum(distances) / len(distances)


# 10. Torfabrik / Beton -----------------------------------------------------

def goal_appetite(bet: Bet) -> float | None:
    """Ø getippte Gesamttorzahl pro Spiel (alle Tipps, nicht nur gespielte)."""
    totals = [t for t in (_total_goals(s) for s in bet.predictions.values()) if t is not None]
    if not totals:
        return None
    return sum(totals) / len(totals)


# Was wäre möglich gewesen -----------------------------------------------

def cumulative_totals(bets: list[Bet], results: Results, matches: list[Match]) -> dict[str, list[int]]:
    """Kumulierte Gesamtpunkte je Spieler nach jedem Spiel 0..104 (Index 0 = Start),
    für den Punkteverlauf-Chart. Der Weiterkommen-Bonus einer Runde wird am letzten
    Spiel der jeweiligen Runde gutgeschrieben (dort ist er im Bracket sichtbar),
    der Weltmeister-Bonus am Finale (#104)."""
    ids = sorted(m.id for m in matches)
    actual = build_bracket(matches, results)
    champion = actual.champion()
    bonus_reveal = {max(round_ids): (round_ids, per) for _, round_ids, per in ADVANCE_ROUNDS}
    final_id = max(ids)

    out: dict[str, list[int]] = {}
    for bet in bets:
        pred_bracket = None
        running = 0
        series = [0]
        for mid in ids:
            actual_score = results.result_for(mid)
            if actual_score is not None:
                pred = bet.prediction_for(mid)
                if pred is not None:
                    running += score_match(pred, actual_score).points
            if mid in bonus_reveal:
                round_ids, per = bonus_reveal[mid]
                if pred_bracket is None:
                    pred_bracket = predicted_bracket(bet, results, matches)
                correct = _round_teams(pred_bracket, round_ids) & _round_teams(actual, round_ids)
                running += len(correct) * per
            if mid == final_id and champion and bet.champion == champion:
                running += CHAMPION_POINTS
            series.append(running)
        out[bet.name] = series
    return out


def max_possible_points(results: Results, matches: list[Match]) -> int:
    """Theoretisches Punktemaximum: perfekte Tipps + Weltmeister + voller
    Weiterkommen-Bonus, auf Basis der tatsächlich eingetragenen Ergebnisse."""
    played = _played_matches(results, matches)
    games_max = 5 * len(played)
    actual = build_bracket(matches, results)
    advancement_max = sum(per * len(_round_teams(actual, ids)) for _, ids, per in ADVANCE_ROUNDS)
    return games_max + CHAMPION_POINTS + advancement_max


# Alles auf einmal -----------------------------------------------------------

@dataclass
class Awards:
    exact_hits: list[tuple[str, int]]
    boldness: list[tuple[str, float]]
    exotic: ExoticHit | None
    worst: WorstTip | None
    ko_oracle: list[tuple[str, int]]
    draw_king: list[tuple[str, int]]
    underdog: list[tuple[str, int]]
    rank_swing: list[tuple[str, int]]
    precision: list[tuple[str, float]]
    goal_appetite: list[tuple[str, float]]
    max_possible: int


def compute_all(bets: list[Bet], results: Results, matches: list[Match]) -> Awards:
    """Berechnet alle 10 Award-Kategorien + Zusatzkennzahlen auf einmal."""
    swing = rank_swing(bets, results, matches)

    def _sorted(values: dict[str, int | float | None], reverse: bool) -> list:
        items = [(name, v) for name, v in values.items() if v is not None]
        items.sort(key=lambda p: p[1], reverse=reverse)
        return items

    return Awards(
        exact_hits=_sorted({b.name: exact_hits(b, results, matches) for b in bets}, reverse=True),
        boldness=_sorted({b.name: boldness_score(b, bets) for b in bets}, reverse=True),
        exotic=exotic_hit(bets, results, matches),
        worst=worst_single_tip(bets, results, matches),
        ko_oracle=_sorted({b.name: ko_points(b, results, matches) for b in bets}, reverse=True),
        draw_king=_sorted({b.name: draw_king(b, results, matches) for b in bets}, reverse=True),
        underdog=_sorted({b.name: underdog_score(b, bets, results, matches) for b in bets}, reverse=True),
        rank_swing=_sorted(swing, reverse=True),
        precision=_sorted({b.name: precision_score(b, results, matches) for b in bets}, reverse=False),
        goal_appetite=_sorted({b.name: goal_appetite(b) for b in bets}, reverse=True),
        max_possible=max_possible_points(results, matches),
    )
