"""Automatischer Ergebnis-Abgleich mit openfootball/worldcup.json.

openfootball pflegt pro Spiel ein strukturiertes Ergebnis:
    "score": { "p": [6,4], "et": [1,1], "ft": [1,1], "ht": [0,1] }
Wir leiten das EINE Endergebnis nach Moris Regel ab:
    Elfer (p) › Verlängerung (et) › reguläre Zeit (ft)
-> damit ist "1:1 n.E. 6:4" automatisch "6:4".

Zugeordnet wird über die Position (gleiche Quelle, gleiche #1–104).
Sicherung: stimmt bei einem Spiel der reale Teamname nicht überein, wird
es übersprungen. Per /result eingetragene Ergebnisse ("manual") bleiben.
"""

import re

import requests

from app.results import load_results, save_results
from app.tournament import Match, load_matches

SOURCE_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

_PLACEHOLDER = re.compile(r"^([12][A-L]|[WL]\d+)$")


def _is_placeholder(name: str) -> bool:
    """Platzhalter wie '2A', 'W74' oder ein Dritten-Slot ('3A/B/...')?"""
    return bool(_PLACEHOLDER.match(name)) or (name.startswith("3") and "/" in name)


def derive_score(score: dict | None) -> str | None:
    """Endergebnis als 'heim:auswaerts' – oder None, wenn Spiel nicht fertig.

    'ft' muss vorhanden sein (= abgepfiffen). Dann gilt: Elfer › Verläng. › 90'."""
    if not score or "ft" not in score:
        return None
    for key in ("p", "et", "ft"):
        value = score.get(key)
        if value:
            return f"{value[0]}:{value[1]}"
    return None


def fetch_remote(url: str = SOURCE_URL, timeout: int = 15) -> dict:
    """Lädt die aktuelle openfootball-Datei."""
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def sync_results(
    matches: list[Match] | None = None, remote: dict | None = None
) -> dict:
    """Gleicht Ergebnisse ab. Gibt eine Zusammenfassung zurück."""
    matches = matches if matches is not None else load_matches()
    remote = remote if remote is not None else fetch_remote()
    remote_matches = remote.get("matches", [])

    summary: dict = {"updated": [], "skipped": [], "remote_count": len(remote_matches)}

    if len(remote_matches) != len(matches):
        summary["error"] = (
            f"Spielanzahl weicht ab (lokal {len(matches)}, remote {len(remote_matches)}) "
            "– Abgleich abgebrochen."
        )
        return summary

    results = load_results()
    for local, rm in zip(matches, remote_matches):
        sid = str(local.id)

        # Sicherung: echte (Nicht-Platzhalter-)Namen müssen übereinstimmen.
        if not _is_placeholder(local.team1) and rm.get("team1") not in (None, local.team1):
            summary["skipped"].append(local.id)
            continue

        value = derive_score(rm.get("score"))
        if value is None:
            continue
        if sid in results.manual:  # von Hand gesetzt -> nicht anfassen
            continue
        if results.matches.get(sid) != value:
            results.matches[sid] = value
            summary["updated"].append((local.id, value))

    if summary["updated"]:
        save_results(results)
    return summary
