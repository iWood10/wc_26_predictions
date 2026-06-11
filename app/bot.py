"""Telegram-Bot des WM-26-Tippspiels.

Befehle:
    /board                  Leaderboard (mit 👑 Weltmeister, sobald er feststeht)
    /champions              wer hat wen als Weltmeister getippt
    /upcoming [name] [n]    nächste offene Spiele + Tipps
    /history [name] [n]     gespielte Spiele + Tipps (mit Name: ✅❌-Detail)
    /result <nr> <ergebnis> Ergebnis eintragen/korrigieren  (z.B. /result 1 2:1)
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
from app.bracket import build_bracket
from app.results import load_results, set_match_result
from app.scoring import parse_score
from app.standings import history, leaderboard, match_tips
from app.sync import sync_results
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


def format_board() -> str:
    bets = load_bets()
    if not bets:
        return "Noch keine Tipps abgegeben."
    results = load_results()
    champion = build_bracket(MATCHES, results).champion()
    ranked = leaderboard(bets, results, champion)

    width = max(len(bet.name) for bet, _ in ranked)
    lines = ["🏆 <b>Leaderboard</b>", "<pre>"]
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
    suffix = f" (vorher {escape(old)})" if old and old != score else ""
    return f"✅ <b>#{match_id}</b> {escape(m.team1)} – {escape(m.team2)}: <b>{score}</b> eingetragen{suffix}"


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


HELP_TEXT = (
    "⚽ <b>WM 26 Tippspiel</b>\n\n"
    "/board – Leaderboard\n"
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
        bot.reply_to(msg, format_board())

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
