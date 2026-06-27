"""Telegram-Bot des WM-26-Tippspiels.

Befehle:
    /board [alt]            Leaderboard (alt = alternative Spiel-Wertung)
    /champions              wer hat wen als Weltmeister getippt
    /upcoming [name] [n]    nächste offene Spiele + Tipps
    /history [name] [n]     gespielte Spiele + Tipps (mit Name: ✅❌-Detail)
    /result <nr> <ergebnis> Ergebnis eintragen/korrigieren  (z.B. /result 1 2:1)
    /ko <name> [nr]         K.o.-Spiele interaktiv durchtippen (nr = eins neu tippen)
    /setthirds              Gruppendritte aus openfootball ableiten -> thirds.json
    /template               leere Tipp-Vorlage (.bet) herunterladen
    /get <name>             Tipp-Datei (.bet) herunterladen
    /getall                 alle Tipp-Dateien als ZIP herunterladen
    /delete <name>          Tipp-Datei löschen
    .bet-Datei(en) schicken Tipp-Datei(en) hochladen/überschreiben
    ZIP schicken            alle enthaltenen Tipps auf einmal hochladen
    /help                   diese Übersicht

Bei /upcoming und /history sind name (Spieler-Filter) und n (Anzahl Spiele)
optional und in beliebiger Reihenfolge.

Ergebnisse werden vor /board, /upcoming und /history automatisch von
openfootball abgeglichen (gedrosselt auf max. 1× pro 60 s).

Token kommt aus der Umgebungsvariable TELEGRAM_BOT_TOKEN (.env-Datei).
Gestartet wird über main.py.
"""

import io
import json
import os
import re
import threading
import time
import zipfile
from datetime import datetime
from html import escape
from pathlib import Path

import telebot
from dotenv import load_dotenv

from app.bets import BET_EXT, BETS_DIR, load_bets
from app.bracket import THIRDS_FILE, build_bracket, load_thirds
from app.results import Results, load_results, set_match_result
from app.scoring import parse_score, score_match, score_match_alt
from app.standings import history, leaderboard, match_tips
from app.sync import _is_placeholder, fetch_remote, sync_results
from app.tournament import load_matches

# Default-Anzahl Spiele für /upcoming und /history ohne Zahl-Argument.
DEFAULT_LIMIT = 10

# Spielplan ist statisch – einmal laden.
MATCHES = load_matches()
MATCHES_BY_ID = {m.id: m for m in MATCHES}

# Anzeige-Namen der 5 Scoring-Kategorien (Reihenfolge wie in scoring.py)
CATEGORY_LEGEND = "Ausgang · Tordiff · Heim · Ausw · Bonus"


# ---------------------------------------------------------------------------
# Formatierung
# ---------------------------------------------------------------------------

def _cats(categories: list[bool]) -> str:
    return "".join("✅" if c else "❌" for c in categories)


def _parse_filter_args(parts: list[str]) -> tuple[str | None, int | None]:
    """Aus den Argumenten Name (erstes Nicht-Zahl-Token) und Limit (erste Zahl)
    ziehen – Reihenfolge egal. z.B. ['mori', '5'] oder ['5', 'mori']."""
    name: str | None = None
    limit: int | None = None
    for token in parts:
        if token.isdigit():
            if limit is None:
                limit = int(token)
        elif name is None:
            name = token
    return name, limit


def _resolve_bet(name: str, bets: list) -> tuple[object | None, str]:
    """Sucht einen Spieler (case-insensitiv). Gibt (bet, fehlertext) zurück –
    bet=None + Fehlertext, wenn es den Namen nicht gibt."""
    bet = next((b for b in bets if b.name.lower() == name.lower()), None)
    if bet is None:
        spieler = ", ".join(escape(b.name) for b in bets) or "—"
        return None, f"Kein Spieler '{escape(name)}' – bekannt: {spieler}"
    return bet, ""


def _tip_line(entries, *, show_points: bool) -> str:
    """Kompakte Tipp-Zeile: 'mori 2:1 · ben 1:1' (mit Punkten wenn show_points)."""
    parts = []
    for e in entries:
        if e.prediction is None:
            continue
        tip = escape(e.prediction)
        name = escape(e.name)
        parts.append(f"{name} {tip} ({e.points})" if show_points else f"{name} {tip}")
    return " · ".join(parts) if parts else "(noch keine Tipps)"


def format_board(alt: bool = False) -> str:
    bets = load_bets()
    if not bets:
        return "Noch keine Tipps abgegeben."
    results = load_results()
    champion = build_bracket(MATCHES, results).champion()
    scorer = score_match_alt if alt else score_match
    ranked = leaderboard(bets, results, champion, scorer)

    width = max(len(bet.name) for bet, _ in ranked)
    title = "🏆 <b>Leaderboard (Alt-Wertung)</b>" if alt else "🏆 <b>Leaderboard</b>"
    lines = [title, "<pre>"]
    for rank, (bet, points) in enumerate(ranked, start=1):
        lines.append(f"{rank}. {escape(f'{bet.name:<{width}}')}  {points:>4}")
    lines.append("</pre>")
    if champion:
        lines.append(f"👑 Weltmeister: <b>{escape(champion)}</b>")
    return "\n".join(lines)


def format_champions() -> str:
    """Wer hat wen als Weltmeister getippt. Treffer wird markiert, sobald
    der echte Champion (aus dem Finale) feststeht."""
    bets = load_bets()
    if not bets:
        return "Noch keine Tipps abgegeben."
    champion = build_bracket(MATCHES, load_results()).champion()

    width = max(len(b.name) for b in bets)
    out = ["👑 <b>Weltmeister-Tipps</b>", "<pre>"]
    for bet in sorted(bets, key=lambda b: b.name.lower()):
        pick = bet.champion or "—"
        hit = " ✅" if champion and bet.champion == champion else ""
        out.append(f"{escape(f'{bet.name:<{width}}')}  → {escape(pick)}{hit}")
    out.append("</pre>")
    if champion:
        out.append(f"Steht fest: <b>{escape(champion)}</b>")
    return "\n".join(out)


def _teams_for(bracket, m) -> tuple[str, str]:
    """Aufgelöste, HTML-escapte Teamnamen (fällt auf den Platzhalter zurück)."""
    t1, t2 = bracket.teams_for(m.id)
    return escape(t1 or m.team1), escape(t2 or m.team2)


def format_upcoming(name: str | None, limit: int | None) -> str:
    """Nächste offene Spiele + Tipps. name filtert auf einen Spieler,
    limit begrenzt die Anzahl Spiele (Default DEFAULT_LIMIT)."""
    bets = load_bets()
    results = load_results()
    bracket = build_bracket(MATCHES, results)

    title = "📅 <b>Nächste offene Spiele</b>"
    if name is not None:
        bet, err = _resolve_bet(name, bets)
        if bet is None:
            return err
        bets = [bet]
        title = f"📅 <b>Nächste Spiele — {escape(bet.name)}</b>"

    pending = [m for m in MATCHES if results.result_for(m.id) is None]
    if not pending:
        return "Alle Spiele sind eingetragen. 🎉"
    pending.sort(key=lambda m: (m.date, m.id))  # chronologisch, nicht nach ID

    out = [title, "<pre>"]
    for m in pending[: limit or DEFAULT_LIMIT]:
        t1, t2 = _teams_for(bracket, m)
        out.append(f"#{m.id} {t1} – {t2}  ({m.date})")
        out.append("   " + _tip_line(match_tips(bets, m.id, None), show_points=False))
    out.append("</pre>")
    return "\n".join(out)


def format_history(name: str | None, limit: int | None) -> str:
    """Gespielte Spiele, neueste zuerst. Ohne Name: alle Tipps kompakt + Ergebnis.
    Mit Name: Detail-Häkchen + Punkte für diesen Spieler."""
    bets = load_bets()
    results = load_results()
    bracket = build_bracket(MATCHES, results)

    if name is not None:
        bet, err = _resolve_bet(name, bets)
        if bet is None:
            return err
        rows = history(bet, results, MATCHES, limit or DEFAULT_LIMIT, bracket)
        if not rows:
            return f"Für {escape(bet.name)} sind noch keine gespielten Spiele da."
        out = [f"📜 <b>History — {escape(bet.name)}</b>", f"<i>{CATEGORY_LEGEND}</i>", ""]
        for r in rows:
            tip = escape(r.prediction) if r.prediction else "—"
            out.append(f"<b>#{r.match_id}</b> {escape(r.team1)} – {escape(r.team2)}  {escape(r.result)}")
            out.append(f"   Tipp {tip} → {r.points} Pkt  {_cats(r.categories)}")
        return "\n".join(out)

    played = [m for m in MATCHES if results.result_for(m.id) is not None]
    if not played:
        return "Noch keine Spiele gespielt."
    played.sort(key=lambda m: (m.date, m.id), reverse=True)  # neueste zuerst (chronologisch)

    out = ["📜 <b>History</b>", "<pre>"]
    for m in played[: limit or DEFAULT_LIMIT]:
        t1, t2 = _teams_for(bracket, m)
        actual = results.result_for(m.id)
        out.append(f"#{m.id} {t1} – {t2}  {escape(actual)}")
        out.append("   " + _tip_line(match_tips(bets, m.id, actual), show_points=True))
    out.append("</pre>")
    return "\n".join(out)


def do_result(args: list[str]) -> str:
    if len(args) != 2:
        return "Nutzung: <code>/result &lt;nr&gt; &lt;ergebnis&gt;</code>\nz.B. <code>/result 1 2:1</code>"
    id_str, score = args
    if not id_str.isdigit() or int(id_str) not in MATCHES_BY_ID:
        return f"Kein Spiel #{escape(id_str)}. Spiele 1–104."
    match_id = int(id_str)

    parsed = parse_score(score)
    if parsed is None:
        return f"Ungültiges Ergebnis '{escape(score)}'. Format: <code>heim:auswärts</code>, z.B. 2:1."
    score = f"{parsed[0]}:{parsed[1]}"  # normalisiert ("2-1" -> "2:1")

    old = load_results().result_for(match_id)
    set_match_result(match_id, score)
    m = MATCHES_BY_ID[match_id]
    # K.o.-Platzhalter ("W74") über den echten Bracket zu Teamnamen auflösen
    t1, t2 = _teams_for(build_bracket(MATCHES, load_results()), m)
    suffix = f" (vorher {escape(old)})" if old and old != score else ""
    return f"✅ <b>#{match_id}</b> {t1} – {t2}: <b>{score}</b> eingetragen{suffix}"


# Lazy-Sync: vor Lese-Befehlen openfootball abgleichen, aber gedrosselt.
SYNC_THROTTLE = 60  # Sekunden – höchstens ein Abruf pro Fenster
_sync_lock = threading.Lock()
_last_sync = 0.0


def _auto_sync() -> None:
    """Best-effort-Abgleich, max. 1× pro SYNC_THROTTLE. Stört Befehle nie."""
    global _last_sync
    with _sync_lock:
        if time.time() - _last_sync < SYNC_THROTTLE:
            return
        _last_sync = time.time()
    try:
        sync_results()
    except Exception as exc:  # Netzwerk/Parse-Fehler dürfen den Befehl nicht stören
        print(f"[auto-sync] Fehler: {exc}")


# Beim Upload erlaubte Endungen (Inhalt ist immer JSON).
UPLOAD_EXTS = (BET_EXT, ".json")

# Papierkorb für gelöschte Tipp-Dateien (load_bets schaut hier nicht rein).
DELETED_DIR = BETS_DIR / "deleted"

# Beispiel-Tipp-Datei im Repo-Root (zum Herunterladen via /template).
TEMPLATE_FILE = BETS_DIR.parent.parent / "template.bet"


def _bet_path(name: str) -> Path:
    """Sicherer Pfad in data/bets/ – nur Dateiname, keine Pfad-Tricks."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "", Path(name).stem)
    return BETS_DIR / f"{safe}{BET_EXT}"


def _validate_bet(data: object) -> str | None:
    """Prüft hochgeladenes Bet-JSON. Gibt Fehlertext zurück, oder None wenn ok."""
    if not isinstance(data, dict):
        return "kein JSON-Objekt"
    preds = data.get("predictions", {})
    if not isinstance(preds, dict):
        return "'predictions' muss ein Objekt sein"
    for key, val in preds.items():
        if not isinstance(val, str):
            return f"Tipp für Spiel {key} ist kein Text (z.B. \"2:1\")"
    return None


def _tip_count(path: Path) -> int | None:
    try:
        return len(json.loads(path.read_text(encoding="utf-8")).get("predictions", {}))
    except Exception:
        return None


def _save_bet(file_name: str, raw: bytes) -> str:
    """Validiert + speichert eine einzelne Tipp-Datei. Gibt die Antwortzeile zurück."""
    label = escape(file_name)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return f"❌ {label}: nicht lesbar ({exc})"
    err = _validate_bet(data)
    if err:
        return f"❌ {label}: {err}"
    path = _bet_path(file_name)
    if path.name == BET_EXT:  # Name auf nichts Gültiges reduziert
        return f"❌ {label}: ungültiger Dateiname (erlaubt: Buchstaben, Zahlen, _ und -)."
    old = _tip_count(path) if path.exists() else None
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    new = len(data.get("predictions", {}))
    suffix = f" (vorher {old})" if old is not None else ""
    return f"✅ <b>{path.name}</b> – {new} Tipps{suffix}"


def _save_zip(raw: bytes) -> str:
    """Entpackt ein hochgeladenes ZIP und speichert alle .bet/.json darin."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except Exception as exc:
        return f"❌ ZIP nicht lesbar: {exc}"
    members = [
        n for n in archive.namelist()
        if not n.endswith("/") and n.lower().endswith(UPLOAD_EXTS)
    ]
    if not members:
        return "❌ ZIP enthält keine .bet/.json-Dateien."
    lines = [_save_bet(Path(n).name, archive.read(n)) for n in members]
    return f"📦 {len(members)} Dateien aus ZIP:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# K.o.-Runde tippen (/ko) – interaktiv, ein Spiel nach dem anderen
# ---------------------------------------------------------------------------

KO_FIRST, KO_LAST = 73, 104  # Spanne der K.o.-Spiel-IDs (Sechzehntel … Finale)

_KO_ROUND_DE = {
    "Round of 32": "Sechzehntelfinale",
    "Round of 16": "Achtelfinale",
    "Quarter-final": "Viertelfinale",
    "Semi-final": "Halbfinale",
    "Match for third place": "Spiel um Platz 3",
    "Final": "Finale",
}


def _load_predictions(name: str) -> dict[str, str]:
    """Tipps eines Spielers frisch von der Platte (Status des K.o.-Flows)."""
    data = json.loads(_bet_path(name).read_text(encoding="utf-8"))
    return data.get("predictions", {})


def _save_ko_pred(name: str, match_id: int, score: str) -> None:
    """Schreibt einen einzelnen K.o.-Tipp in die .bet-Datei des Spielers."""
    path = _bet_path(name)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("predictions", {})[str(match_id)] = score
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _ko_describe(bracket, token: str) -> tuple[str, str | None]:
    """(Feeder-Label, aufgelöstes Team) für einen K.o.-Platzhalter.

    'W74'/'L101' → Feeder = beide Teams des Quellspiels ('A/B'), Team = Sieger/Verlierer.
    Gruppen-Slot ('1E', '3A/B/...') → Feeder == aufgelöstes Team."""
    resolved = bracket.resolve_token(token)
    m = re.match(r"^[WL](\d+)$", token)
    if m:
        t1, t2 = bracket.teams_for(int(m.group(1)))
        return f"{t1 or '?'}/{t2 or '?'}", resolved
    return resolved or "?", resolved


def _ko_prompt(match, bracket) -> str:
    """Anzeige einer K.o.-Paarung, aufgelöst aus den Tipps des Spielers."""
    rnd = _KO_ROUND_DE.get(match.round, match.round)
    a_feeder, a_team = _ko_describe(bracket, match.team1)
    b_feeder, b_team = _ko_describe(bracket, match.team2)
    head = f"🏆 <b>{rnd}</b> — #{match.id}"
    if match.round == "Round of 32":  # beide Seiten direkt aus den Gruppen
        body = f"<b>{escape(a_team or '?')} – {escape(b_team or '?')}</b>"
    else:
        body = (
            f"{escape(a_feeder)}  vs  {escape(b_feeder)}\n"
            f"laut deinen Tipps: <b>{escape(a_team or '?')} – {escape(b_team or '?')}</b>"
        )
    return f"{head}\n{body}\n\nErgebnis? (z.B. <code>2:1</code>)"


def ko_present(bot, chat_id: int, name: str, match_id: int, advance: bool) -> None:
    """Zeigt ein bestimmtes K.o.-Spiel und wartet auf das Ergebnis.
    advance=True → danach automatisch zum nächsten offenen Spiel."""
    bracket = build_bracket(MATCHES, Results(matches=dict(_load_predictions(name))))
    bot.send_message(chat_id, _ko_prompt(MATCHES_BY_ID[match_id], bracket))
    bot.register_next_step_handler_by_chat_id(
        chat_id, lambda m: ko_step(bot, m, name, match_id, advance)
    )


def ko_send_next(bot, chat_id: int, name: str) -> None:
    """Schickt das nächste noch nicht getippte K.o.-Spiel – oder meldet 'fertig'."""
    preds = _load_predictions(name)
    match_id = next(
        (i for i in range(KO_FIRST, KO_LAST + 1) if str(i) not in preds), None
    )
    if match_id is None:
        bot.send_message(chat_id, f"🏁 Alle K.o.-Spiele für <b>{escape(name)}</b> sind getippt!")
        return
    ko_present(bot, chat_id, name, match_id, advance=True)


def ko_step(bot, msg, name: str, match_id: int, advance: bool = True) -> None:
    """Verarbeitet die Antwort auf ein K.o.-Spiel im laufenden /ko-Flow."""
    text = (msg.text or "").strip()
    parsed = parse_score(text)
    if parsed is None:
        # Kein Ergebnis → Session pausiert. Befehle normal weiterlaufen lassen.
        if text.startswith("/"):
            try:
                bot.process_new_messages([msg])
            except Exception:  # Passthrough darf den Bot nie hängen lassen
                bot.reply_to(msg, f"⏸️ K.o.-Tippen pausiert – <code>/ko {escape(name)}</code> setzt fort.")
        else:
            bot.reply_to(msg, f"⏸️ K.o.-Tippen pausiert – <code>/ko {escape(name)}</code> setzt fort.")
        return
    h, a = parsed
    if h == a:
        bot.reply_to(msg, "K.o.-Spiel braucht einen Sieger (Elfmeterschießen entscheidet). Nochmal:")
        bot.register_next_step_handler_by_chat_id(
            msg.chat.id, lambda m: ko_step(bot, m, name, match_id, advance)
        )
        return
    score = f"{h}:{a}"
    old = _load_predictions(name).get(str(match_id))
    _save_ko_pred(name, match_id, score)
    note = f" (vorher {escape(old)})" if old and old != score else ""
    bot.reply_to(msg, f"✅ #{match_id}: <b>{score}</b>{note}")
    if advance:
        ko_send_next(bot, msg.chat.id, name)


def _slot_groups(token: str) -> set[str]:
    """Erlaubte Gruppenbuchstaben eines Dritten-Slots: '3A/B/C/D/F' -> {A,B,C,D,F}."""
    return set(token[1:].split("/"))


def do_setthirds() -> str:
    """Leitet data/thirds.json aus den von openfootball aufgelösten K.o.-Paarungen ab.

    Für jedes Sechzehntel mit Dritten-Slot wird das reale Team aus der API gelesen,
    seiner Gruppe zugeordnet und als Slot→Buchstabe gespeichert. Schreibt nur, wenn
    alle 8 Slots aufgelöst und gültig sind."""
    try:
        remote = fetch_remote()
    except Exception as exc:
        return f"❌ Konnte openfootball nicht laden: {escape(str(exc))}"
    rm = remote.get("matches", [])
    if len(rm) != len(MATCHES):
        return f"❌ Spielanzahl weicht ab (lokal {len(MATCHES)}, remote {len(rm)}) – abgebrochen."

    # Team -> Gruppenbuchstabe aus den Gruppenspielen der API
    team_group: dict[str, str] = {}
    for m in rm:
        grp = m.get("group")
        if grp:
            letter = grp.replace("Group ", "")
            for t in (m.get("team1"), m.get("team2")):
                if t:
                    team_group[t] = letter

    mapping: dict[str, str] = {}
    open_slots: list[str] = []
    errors: list[str] = []

    for local in MATCHES:
        for idx, token in enumerate((local.team1, local.team2)):
            if not (token.startswith("3") and "/" in token):
                continue  # nur Dritten-Slots
            remote_team = (rm[local.id - 1].get("team1"), rm[local.id - 1].get("team2"))[idx]
            if not remote_team or _is_placeholder(remote_team):
                open_slots.append(f"#{local.id} {token}")
                continue
            letter = team_group.get(remote_team)
            if letter is None:
                errors.append(f"#{local.id}: '{escape(remote_team)}' keiner Gruppe zuzuordnen")
            elif letter not in _slot_groups(token):
                errors.append(f"#{local.id} {token}: {escape(remote_team)} (Gruppe {letter}) nicht erlaubt")
            else:
                mapping[token] = letter

    # Jede Gruppe darf nur einen Slot füllen
    seen: dict[str, str] = {}
    for slot, letter in mapping.items():
        if letter in seen:
            errors.append(f"Gruppe {letter} doppelt ({seen[letter]} & {slot})")
        seen[letter] = slot

    if errors:
        return "❌ Probleme beim Ableiten:\n" + "\n".join(errors)
    if open_slots:
        return (
            f"⏳ openfootball noch nicht so weit – {len(open_slots)} von 8 "
            "Dritten-Slots offen:\n" + "\n".join(open_slots) + "\n\nSpäter nochmal /setthirds."
        )

    THIRDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    THIRDS_FILE.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = "\n".join(f"{slot} → Gruppe {letter}" for slot, letter in mapping.items())
    return f"✅ <b>thirds.json gesetzt</b> – K.o.-Tippen freigeschaltet:\n<pre>{lines}</pre>"


HELP_TEXT = (
    "⚽ <b>WM 26 Tippspiel</b>\n\n"
    "/board – Leaderboard\n"
    "/board alt – Leaderboard mit alternativer Wertung\n"
    "/champions – wer hat wen als Weltmeister getippt\n"
    "/upcoming [name] [n] – nächste offene Spiele + Tipps\n"
    "/history [name] [n] – gespielte Spiele + Tipps\n"
    "<i>name filtert auf einen Spieler, n = wie viele Spiele.</i>\n\n"
    "/help – diese Übersicht\n"
    "<i>Verwalten: /help advanced</i>"
)

ADVANCED_HELP_TEXT = (
    "🔧 <b>Erweitert – Verwalten</b>\n\n"
    "/result &lt;nr&gt; &lt;ergebnis&gt; – Ergebnis eintragen (z.B. /result 1 2:1)\n"
    "/ko &lt;name&gt; [nr] – K.o.-Spiele durchtippen (nr = ein Spiel neu tippen)\n"
    "/setthirds – Gruppendritte aus openfootball ableiten (schaltet /ko frei)\n"
    "/template – leere Tipp-Vorlage (.bet) herunterladen\n"
    "/get &lt;name&gt; – Tipp-Datei (.bet) herunterladen\n"
    "/getall – alle Tipp-Dateien als ZIP herunterladen\n"
    "/delete &lt;name&gt; – Tipp-Datei löschen (Papierkorb)\n"
    ".bet-Datei(en) schicken – Tipps hochladen/überschreiben\n"
    "ZIP schicken – alle enthaltenen Tipps auf einmal hochladen"
)


# ---------------------------------------------------------------------------
# Bot-Verdrahtung
# ---------------------------------------------------------------------------

def build_bot() -> telebot.TeleBot:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN fehlt – in .env eintragen.")

    bot = telebot.TeleBot(token, parse_mode="HTML")

    @bot.message_handler(commands=["start", "help"])
    def _help(msg):
        parts = msg.text.split()
        if len(parts) > 1 and parts[1].lower().startswith("adv"):
            bot.reply_to(msg, ADVANCED_HELP_TEXT)
        else:
            bot.reply_to(msg, HELP_TEXT)

    @bot.message_handler(commands=["board"])
    def _board(msg):
        _auto_sync()
        parts = msg.text.split()
        alt = len(parts) > 1 and parts[1].lower().startswith("alt")
        bot.reply_to(msg, format_board(alt))

    @bot.message_handler(commands=["champions"])
    def _champions(msg):
        _auto_sync()
        bot.reply_to(msg, format_champions())

    @bot.message_handler(commands=["upcoming"])
    def _upcoming(msg):
        _auto_sync()
        name, limit = _parse_filter_args(msg.text.split()[1:])
        bot.reply_to(msg, format_upcoming(name, limit))

    @bot.message_handler(commands=["history"])
    def _history(msg):
        _auto_sync()
        name, limit = _parse_filter_args(msg.text.split()[1:])
        bot.reply_to(msg, format_history(name, limit))

    @bot.message_handler(commands=["result"])
    def _result(msg):
        args = msg.text.split()[1:]
        bot.reply_to(msg, do_result(args))

    @bot.message_handler(commands=["setthirds"])
    def _setthirds(msg):
        bot.reply_to(msg, do_setthirds())

    @bot.message_handler(commands=["ko"])
    def _ko(msg):
        if msg.chat.type != "private":
            bot.reply_to(
                msg,
                "🔒 K.o.-Tippen geht nur im Direktchat mit mir (sonst kollidieren "
                "mehrere Tipper). Schreib mir privat: <code>/ko &lt;name&gt;</code>",
            )
            return
        parts = msg.text.split()
        if len(parts) < 2:
            names = ", ".join(escape(b.name) for b in load_bets()) or "—"
            bot.reply_to(msg, f"Nutzung: <code>/ko &lt;name&gt;</code>\nVorhanden: {names}")
            return
        name = parts[1]
        if not _bet_path(name).exists():
            bot.reply_to(msg, f"Kein Tipp-File '{escape(name)}'.")
            return
        if not load_thirds():
            bot.reply_to(
                msg,
                "🔒 K.o.-Tippen ist noch nicht freigeschaltet – die Gruppendritten "
                "stehen noch nicht fest.",
            )
            return
        if len(parts) >= 3:  # gezielt ein Spiel neu tippen: /ko <name> <nr>
            if not parts[2].isdigit() or not (KO_FIRST <= int(parts[2]) <= KO_LAST):
                bot.reply_to(msg, f"K.o.-Spiel-Nr muss zwischen {KO_FIRST} und {KO_LAST} liegen.")
                return
            ko_present(bot, msg.chat.id, name, int(parts[2]), advance=False)
            return
        ko_send_next(bot, msg.chat.id, name)

    @bot.message_handler(commands=["template"])
    def _template(msg):
        if not TEMPLATE_FILE.exists():
            bot.reply_to(msg, "Kein Template vorhanden.")
            return
        with open(TEMPLATE_FILE, "rb") as f:
            bot.send_document(
                msg.chat.id,
                f,
                visible_file_name="template.bet",
                caption=(
                    "📄 Vorlage – ausfüllen, in <b>deinname.bet</b> umbenennen "
                    "(Dateiname = Spielername!) und zurückschicken."
                ),
            )

    @bot.message_handler(commands=["get"])
    def _get(msg):
        parts = msg.text.split()
        if len(parts) < 2:
            names = ", ".join(escape(b.name) for b in load_bets()) or "—"
            bot.reply_to(msg, f"Nutzung: <code>/get &lt;name&gt;</code>\nVorhanden: {names}")
            return
        path = _bet_path(parts[1])
        if not path.exists():
            bot.reply_to(msg, f"Kein Tipp-File '{escape(parts[1])}'.")
            return
        with open(path, "rb") as f:
            bot.send_document(msg.chat.id, f, visible_file_name=path.name, caption=f"📄 {path.name}")

    @bot.message_handler(commands=["getall"])
    def _getall(msg):
        paths = sorted(BETS_DIR.glob(f"*{BET_EXT}"))
        if not paths:
            bot.reply_to(msg, "Keine Tipp-Dateien vorhanden.")
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in paths:
                zf.write(p, arcname=p.name)
        buf.seek(0)
        bot.send_document(
            msg.chat.id,
            buf,
            visible_file_name="bets.zip",
            caption=f"📦 {len(paths)} Tipp-Dateien – zum Wiederherstellen einfach zurückschicken.",
        )

    @bot.message_handler(content_types=["document"])
    def _upload(msg):
        doc = msg.document
        fname = doc.file_name.lower()
        if not fname.endswith(UPLOAD_EXTS) and not fname.endswith(".zip"):
            return  # andere Dateien still ignorieren (z.B. in Gruppenchats)
        try:
            info = bot.get_file(doc.file_id)
            raw = bot.download_file(info.file_path)
        except Exception as exc:
            bot.reply_to(msg, f"❌ Konnte Datei nicht lesen: {exc}")
            return
        if fname.endswith(".zip"):
            bot.reply_to(msg, _save_zip(raw))
        else:
            bot.reply_to(msg, _save_bet(doc.file_name, raw))

    @bot.message_handler(commands=["delete"])
    def _delete(msg):
        parts = msg.text.split()
        if len(parts) < 2:
            names = ", ".join(escape(b.name) for b in load_bets()) or "—"
            bot.reply_to(msg, f"Nutzung: <code>/delete &lt;name&gt;</code>\nVorhanden: {names}")
            return
        path = _bet_path(parts[1])
        if not path.exists():
            bot.reply_to(msg, f"Kein Tipp-File '{escape(parts[1])}'.")
            return
        tips = _tip_count(path)
        DELETED_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path.rename(DELETED_DIR / f"{path.stem}_{stamp}{BET_EXT}")
        info = f" ({tips} Tipps)" if tips is not None else ""
        bot.reply_to(
            msg,
            f"🗑️ <b>{path.name}</b>{info} gelöscht – liegt im Papierkorb "
            f"(<code>bets/deleted/</code>), wiederherstellbar.",
        )

    return bot


def run() -> None:
    bot = build_bot()
    print(f"Bot läuft – Lazy-Sync (max. 1×/{SYNC_THROTTLE}s) … (Strg+C zum Beenden)")
    bot.infinity_polling()
