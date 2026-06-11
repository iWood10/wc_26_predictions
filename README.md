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

Plus **50 Punkte** für den richtigen Weltmeister (wird automatisch aus dem
Finale abgeleitet). K.o.-Spiele: nur das Endergebnis zählt (inkl. Verlängerung/
Elfmeterschießen).

## Befehle

| Befehl | Zweck |
|---|---|
| `/board` | Leaderboard (mit 👑 Weltmeister, sobald er feststeht) |
| `/champions` | wer hat wen als Weltmeister getippt |
| `/upcoming [name] [n]` | nächste offene Spiele + Tipps |
| `/history [name] [n]` | gespielte Spiele + Tipps (mit Name: Kategorie-Häkchen) |
| `/result <nr> <ergebnis>` | Ergebnis eintragen/korrigieren (z.B. `/result 1 2:1`) |
| `/get <name>` | Tipp-Datei (`.bet`) herunterladen |
| `/getall` | alle Tipp-Dateien als ZIP herunterladen |
| `/delete <name>` | Tipp-Datei löschen (Papierkorb) |
| `.bet`-Datei(en) schicken | Tipps hochladen/überschreiben (mehrere gleichzeitig möglich) |
| ZIP schicken | alle enthaltenen Tipps auf einmal hochladen |
| `/help` / `/help advanced` | Hilfe (einfach / Verwalten) |

Bei `/upcoming` und `/history` sind **name** (Spieler-Filter) und **n** (Anzahl
Spiele) optional und in beliebiger Reihenfolge, z.B. `/upcoming mori 5`.

Vor `/board`, `/history`, `/upcoming` werden die Ergebnisse automatisch von
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

## Deployment (Docker)

Auf dem Server (Repo ist öffentlich, Clone ohne Auth):

```bash
git clone https://github.com/iWood10/wc_26_predictions.git
cd wc_26_predictions
echo "TELEGRAM_BOT_TOKEN=dein:token" > .env   # Token einmalig anlegen
docker compose up -d --build
```

`restart: unless-stopped` hält den Bot am Leben (Crash + Server-Reboot).
Die Tipps/Ergebnisse liegen per Volume in `./data` auf dem Host und überleben
Redeploys.

**Update bei neuem Code:**

```bash
git pull && docker compose up -d --build
```

`git pull` berührt nie die Laufzeit-Daten (die sind gitignored).

## Daten

- `data/tournament.json` – Spielplan + Gruppen (Quelle: openfootball, im Repo).
- `data/bets/<name>.bet` – Tipps je Spieler (JSON-Inhalt). **Nicht** in git –
  werden über den Bot gepflegt. Format-Beispiel: [`template.bet`](template.bet)
  (`predictions`: Spiel-Nr → `"heim:auswärts"`, dazu `champion`).
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
