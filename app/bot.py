"""Telegram-Bot des WM-26-Tippspiels.

Befehle:
    /board                  Leaderboard (mit 👑 Weltmeister, sobald er feststeht)
    /history <name> [n]     Tipp-Historie eines Spielers (mit ✅❌)
    /matches [n]            nächste offene Spiele
    /result <nr> <ergebnis> Ergebnis eintragen/korrigieren  (z.B. /result 1 2:1)
    /get <name>             Tipp-Datei (.bet) herunterladen
    /delete <name>          Tipp-Datei löschen
    .bet-Datei schicken     Tipp-Datei hochladen/überschreiben
    /help                   diese Übersicht

Ergebnisse werden vor /board, /history und /matches automatisch von
openfootball abgeglichen (gedrosselt auf max. 1× pro 60 s).

Token kommt aus der Umgebungsvariable TELEGRAM_BOT_TOKEN (.env-Datei).
Gestartet wird über main.py.
"""

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import telebot
from dotenv import load_dotenv

from app.bets import BET_EXT, BETS_DIR, load_bets
from app.bracket import build_bracket
from app.results import load_results, set_match_result
from app.standings import history, leaderboard
from app.sync import sync_results
from app.tournament import load_matches

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
        lines.append(f"{rank}. {bet.name:<{width}}  {points:>4}")
    lines.append("</pre>")
    if champion:
        lines.append(f"👑 Weltmeister: <b>{champion}</b>")
    return "\n".join(lines)


def format_history(name: str, limit: int | None) -> str:
    bet = next((b for b in load_bets() if b.name.lower() == name.lower()), None)
    if bet is None:
        spieler = ", ".join(b.name for b in load_bets()) or "—"
        return f"Kein Spieler '{name}' – bekannt: {spieler}"

    results = load_results()
    bracket = build_bracket(MATCHES, results)
    rows = history(bet, results, MATCHES, limit, bracket)
    if not rows:
        return f"Für {bet.name} sind noch keine gespielten Spiele da."

    out = [f"📜 <b>History — {bet.name}</b>", f"<i>{CATEGORY_LEGEND}</i>", ""]
    for r in rows:
        tip = r.prediction or "—"
        out.append(f"<b>#{r.match_id}</b> {r.team1} – {r.team2}  {r.result}")
        out.append(f"   Tipp {tip} → {r.points} Pkt  {_cats(r.categories)}")
    return "\n".join(out)


def format_matches(limit: int = 10) -> str:
    results = load_results()
    bracket = build_bracket(MATCHES, results)
    bets = load_bets()
    pending = [m for m in MATCHES if results.result_for(m.id) is None]
    if not pending:
        return "Alle Spiele sind eingetragen. 🎉"

    out = ["📅 <b>Nächste offene Spiele</b>", "<pre>"]
    for m in pending[:limit]:
        t1, t2 = bracket.teams_for(m.id)
        out.append(f"#{m.id} {(t1 or m.team1)} – {(t2 or m.team2)}  ({m.date})")
        tips = [f"{b.name} {b.prediction_for(m.id)}" for b in bets if b.prediction_for(m.id)]
        out.append("   " + (" · ".join(tips) if tips else "(noch keine Tipps)"))
    out.append("</pre>")
    return "\n".join(out)


def do_result(args: list[str]) -> str:
    if len(args) != 2:
        return "Nutzung: <code>/result &lt;nr&gt; &lt;ergebnis&gt;</code>\nz.B. <code>/result 1 2:1</code>"
    id_str, score = args
    if not id_str.isdigit() or int(id_str) not in MATCHES_BY_ID:
        return f"Kein Spiel #{id_str}. Spiele 1–104."
    match_id = int(id_str)

    old = load_results().result_for(match_id)
    set_match_result(match_id, score)
    m = MATCHES_BY_ID[match_id]
    suffix = f" (vorher {old})" if old and old != score else ""
    return f"✅ <b>#{match_id}</b> {m.team1} – {m.team2}: <b>{score}</b> eingetragen{suffix}"


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


HELP_TEXT = (
    "⚽ <b>WM 26 Tippspiel</b>\n\n"
    "/board – Leaderboard\n"
    "/history &lt;name&gt; [n] – Tipp-Historie\n"
    "/matches [n] – nächste offene Spiele\n"
    "/help – diese Übersicht\n\n"
    "<i>Verwalten: /help advanced</i>"
)

ADVANCED_HELP_TEXT = (
    "🔧 <b>Erweitert – Verwalten</b>\n\n"
    "/result &lt;nr&gt; &lt;ergebnis&gt; – Ergebnis eintragen (z.B. /result 1 2:1)\n"
    "/get &lt;name&gt; – Tipp-Datei (.bet) herunterladen\n"
    "/delete &lt;name&gt; – Tipp-Datei löschen (Papierkorb)\n"
    ".bet-Datei schicken – Tipps hochladen/überschreiben"
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

    @bot.message_handler(commands=["matches"])
    def _matches(msg):
        _auto_sync()
        parts = msg.text.split()
        limit = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
        bot.reply_to(msg, format_matches(limit))

    @bot.message_handler(commands=["history"])
    def _history(msg):
        _auto_sync()
        parts = msg.text.split()
        if len(parts) < 2:
            bot.reply_to(msg, "Nutzung: <code>/history &lt;name&gt; [n]</code>")
            return
        name = parts[1]
        limit = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        bot.reply_to(msg, format_history(name, limit))

    @bot.message_handler(commands=["result"])
    def _result(msg):
        args = msg.text.split()[1:]
        bot.reply_to(msg, do_result(args))

    @bot.message_handler(commands=["get"])
    def _get(msg):
        parts = msg.text.split()
        if len(parts) < 2:
            names = ", ".join(b.name for b in load_bets()) or "—"
            bot.reply_to(msg, f"Nutzung: <code>/get &lt;name&gt;</code>\nVorhanden: {names}")
            return
        path = _bet_path(parts[1])
        if not path.exists():
            bot.reply_to(msg, f"Kein Tipp-File '{parts[1]}'.")
            return
        with open(path, "rb") as f:
            bot.send_document(msg.chat.id, f, visible_file_name=path.name, caption=f"📄 {path.name}")

    @bot.message_handler(content_types=["document"])
    def _upload(msg):
        doc = msg.document
        if not doc.file_name.lower().endswith(UPLOAD_EXTS):
            return  # andere Dateien still ignorieren (z.B. in Gruppenchats)
        try:
            info = bot.get_file(doc.file_id)
            data = json.loads(bot.download_file(info.file_path).decode("utf-8"))
        except Exception as exc:
            bot.reply_to(msg, f"❌ Konnte Datei nicht lesen: {exc}")
            return
        err = _validate_bet(data)
        if err:
            bot.reply_to(msg, f"❌ Datei abgelehnt: {err}")
            return
        path = _bet_path(doc.file_name)
        old = _tip_count(path) if path.exists() else None
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        new = len(data.get("predictions", {}))
        suffix = f" (vorher {old})" if old is not None else ""
        bot.reply_to(msg, f"✅ <b>{path.name}</b> gespeichert – {new} Tipps{suffix}")

    @bot.message_handler(commands=["delete"])
    def _delete(msg):
        parts = msg.text.split()
        if len(parts) < 2:
            names = ", ".join(b.name for b in load_bets()) or "—"
            bot.reply_to(msg, f"Nutzung: <code>/delete &lt;name&gt;</code>\nVorhanden: {names}")
            return
        path = _bet_path(parts[1])
        if not path.exists():
            bot.reply_to(msg, f"Kein Tipp-File '{parts[1]}'.")
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
