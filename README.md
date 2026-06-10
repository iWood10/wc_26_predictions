# WM 2026 Tippspiel – Telegram-Bot

Ein Telegram-Bot, der unser Tippspiel zur Fußball-WM 2026 verwaltet:
Ergebnisse, Punkte, Leaderboard und Tipp-Historie – direkt im Chat.

## Scoring

Pro Spiel max. **5 Punkte**:

| Kriterium | Punkte |
|---|---|
| Richtiger Ausgang (Sieg/Unentschieden/Niederlage) | 1 |
| Richtige Tordifferenz | 1 |
| Tore Heim absolut | 1 |
| Tore Auswärts absolut | 1 |
| Bonus: exaktes Ergebnis (alle vier richtig) | 1 |

Plus **65 Punkte** für den richtigen Weltmeister (wird automatisch aus dem
Finale abgeleitet). K.o.-Spiele: nur das Endergebnis zählt (inkl. Verlängerung/
Elfmeterschießen).

## Befehle

| Befehl | Zweck |
|---|---|
| `/board` | Leaderboard (mit 👑 Weltmeister, sobald er feststeht) |
| `/history <name> [n]` | Tipp-Historie eines Spielers mit Kategorie-Häkchen |
| `/matches [n]` | nächste offene Spiele + wie alle getippt haben |
| `/result <nr> <ergebnis>` | Ergebnis eintragen/korrigieren (z.B. `/result 1 2:1`) |
| `/get <name>` | Tipp-Datei (`.bet`) herunterladen |
| `/delete <name>` | Tipp-Datei löschen (Papierkorb) |
| `.bet`-Datei schicken | Tipps hochladen/überschreiben |
| `/help` / `/help advanced` | Hilfe (einfach / Verwalten) |

Vor `/board`, `/history`, `/matches` werden die Ergebnisse automatisch von
[openfootball](https://github.com/openfootball/worldcup.json) abgeglichen
(gedrosselt auf max. 1× pro 60 s). `/result` überschreibt der Auto-Sync nie.

## Einrichtung

Voraussetzungen: [uv](https://docs.astral.sh/uv/) und ein Bot-Token von
[@BotFather](https://t.me/BotFather).

```bash
uv sync                          # Abhängigkeiten installieren
echo "TELEGRAM_BOT_TOKEN=dein:token" > .env
uv run main.py                   # Bot starten
```

## Daten

- `data/tournament.json` – Spielplan + Gruppen (Quelle: openfootball, im Repo).
- `data/bets/<name>.bet` – Tipps je Spieler (JSON-Inhalt). **Nicht** in git –
  werden über den Bot gepflegt.
- `data/results.json` – eingetragene Ergebnisse. **Nicht** in git.
- `data/thirds.json` – Zuordnung der besten Gruppendritten (einmalig Ende der
  Vorrunde zu setzen). **Nicht** in git.

Laufzeit-Daten liegen bewusst außerhalb von git, damit ein `git pull` auf dem
Server nie mit den Live-Änderungen kollidiert.

## Projektstruktur

```
app/
  tournament.py  Spielplan laden
  scoring.py     5-Kriterien-Bewertung
  groups.py      Gruppentabellen
  bracket.py     K.o.-Platzhalter → echte Teams, Champion
  bets.py        Tipps laden
  results.py     Ergebnisse laden/speichern
  standings.py   Leaderboard + History
  sync.py        Ergebnis-Abgleich mit openfootball
  bot.py         Telegram-Oberfläche
main.py          Startet den Bot
```
