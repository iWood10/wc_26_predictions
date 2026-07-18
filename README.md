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

Plus **30 Punkte** für den richtigen Weltmeister (wird automatisch aus dem
Finale abgeleitet). K.o.-Spiele: nur das Endergebnis zählt (inkl. Verlängerung/
Elfmeterschießen).

### Weiterkommen-Bonus (K.o.-Runden)

Zusätzlich Punkte dafür, **welche Teams eine Runde erreichen** – je richtig
vorhergesagtem Team (aus den eigenen K.o.-Tipps):

| Runde | Punkte je Team |
|---|---|
| Achtelfinale | 1 |
| Viertelfinale | 2 |
| Halbfinale | 3 |
| Finale | 5 |

Pro Runde wird die Menge der Teams, die *laut den eigenen Tipps* dort steht, mit
den *tatsächlich* dort stehenden Teams geschnitten (Reihenfolge egal). Die R32-Paarungen
stehen über die Gruppenergebnisse fest; die K.o.-Sieger kommen aus den `/ko`-Tipps.
Fehlt ein Tipp, bricht der Zweig ab – daraus lässt sich kein Team einer späteren Runde
vorhersagen (keine Punkte). Der Bonus zählt in die `/board`-Gesamtwertung.
**`/bonus`** zeigt die Gesamtübersicht (richtige Teams je Runde pro Spieler),
**`/bonus <name>`** die Runden-Aufschlüsselung eines Spielers.

### Alternative Wertung (`/board alt`)

Gleicher Max (5 Punkte/Spiel), aber leicht andere Kriterien:

| Kriterium | Punkte |
|---|---|
| Richtiger Ausgang (Sieg/Unentschieden/Niederlage) | 1 |
| Richtige Tordifferenz | 1 |
| Richtige Toranzahl einer Seite (Heim **oder** Auswärts **oder** beide) | 1 |
| Richtige Gesamtzahl Tore (Heim + Auswärts) | 1 |
| Bonus: wenn alle vier stimmen | 1 |

Der Weltmeister-Bonus (30) bleibt gleich. `/board alt` ändert nur die Spiel-Wertung
und schreibt nichts – es ist eine reine Vergleichsansicht.

## Befehle

| Befehl | Zweck |
|---|---|
| `/board` | Leaderboard (mit 👑 Weltmeister, sobald er feststeht) |
| `/board alt` | Leaderboard mit alternativer Spiel-Wertung (s.u.) |
| `/champions` | wer hat wen als Weltmeister getippt |
| `/bonus [name]` | Weiterkommen-Bonus (Übersicht, oder je Runde mit Name) |
| `/upcoming [name] [n]` | nächste offene Spiele + Tipps |
| `/history [name] [n]` | gespielte Spiele + Tipps (mit Name: Kategorie-Häkchen) |
| `/result <nr> <ergebnis>` | Ergebnis eintragen/korrigieren (z.B. `/result 1 2:1`) |
| `/ko <name> [nr]` | K.o.-Spiele durchtippen (`nr` = ein Spiel neu tippen) |
| `/get <name>` | Tipp-Datei (`.bet`) herunterladen |
| `/getall` | alle Tipp-Dateien als ZIP herunterladen |
| `/delete <name>` | Tipp-Datei löschen (Papierkorb) |
| `.bet`-Datei(en) schicken | Tipps hochladen/überschreiben (mehrere gleichzeitig möglich) |
| ZIP schicken | alle enthaltenen Tipps auf einmal hochladen |
| `/help` / `/help advanced` | Hilfe (einfach / Verwalten) |

Bei `/upcoming` und `/history` sind **name** (Spieler-Filter) und **n** (Anzahl
Spiele) optional und in beliebiger Reihenfolge, z.B. `/upcoming mori 5`.

### K.o.-Runde tippen (`/ko <name>`)

Interaktiv, ein Spiel nach dem anderen: Der Bot zeigt die Paarung – **aufgelöst aus
den eigenen Tipps des Spielers** (Gruppentabellen + bisherige K.o.-Sieger) – und man
antwortet mit dem Ergebnis (`7:1`). Sechzehntel: `Deutschland – Schottland`; höhere
Runden zeigen die Quell-Paarung plus die resultierenden Teams. Reihenfolge: alle
Sechzehntel → Achtel → Viertel → … → Finale (IDs 73–104).

- Bricht man ab (anderer Befehl, keine Antwort), pausiert der Flow. `/ko <name>`
  setzt fort, wo das erste Ergebnis fehlt – der Status steckt in der `.bet`.
- `/ko <name> <nr>` tippt gezielt **ein** Spiel (73–104) neu (z.B. Tippfehler
  korrigieren) und stoppt danach; zeigt den vorherigen Tipp mit an.
- K.o.-Spiele brauchen einen Sieger: ein Unentschieden wird abgelehnt (Elfmeterschießen).
- **Freigeschaltet erst, wenn `data/thirds.json` gesetzt ist** (Ende der Vorrunde) –
  vorher können die Gruppendritten-Gegner im Sechzehntelfinale nicht aufgelöst werden.
  Die Datei ordnet jeden Dritten-Slot einem Gruppenbuchstaben zu (`Slot → Gruppe`,
  z.B. `"3A/B/C/D/F": "D"`) und wird einmalig nach der Vorrunde anhand der offiziellen
  Auslosung gesetzt.
- Am besten im **Direktchat** mit dem Bot nutzen (der Flow merkt sich den nächsten
  Schritt pro Chat).

Vor `/board`, `/history`, `/upcoming` werden die Ergebnisse automatisch von
[openfootball](https://github.com/openfootball/worldcup.json) abgeglichen
(gedrosselt auf max. 1× pro 60 s). `/result` überschreibt der Auto-Sync nie.

### Finale Edition

Sobald **alle 104 Spiele** ein Ergebnis haben, liefert `/board` (ohne `alt`)
automatisch eine große Zusammenfassung statt des normalen Leaderboards –
kein eigener Befehl, kein Hintergrund-Job, nur eine Prüfung im `/board`-Handler:

- 👑 Weltmeister + wer ihn richtig getippt hat
- Endstand **aller** Spieler mit Punkte-Aufschlüsselung (Spiele / WM-Bonus / Weiterkommen-Bonus)
- ein Chart als Bild: Punkteverlauf über die 104 Spiele, relativ zum Gruppen-
  schnitt (gemeinsame Steigung rausgerechnet, nur die relative Position bleibt sichtbar)
- 10 Auszeichnungen (meiste exakte Tipps, mutigster Tipper, exotischster Treffer,
  schlechtester Tipp, Orakel der K.o.-Runde, Remis-König, Underdog-Riecher,
  Aufholjagd/Absturz, der Genaue, Torfabrik/Beton)
- „Was möglich gewesen wäre" – das theoretische Punktemaximum

Die Berechnungen stecken in `app/awards.py` (reine Funktionen, kein I/O), das
Chart-Rendering in `app/chart.py` (matplotlib, PNG für `bot.send_photo`).

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
  Vorrunde zu setzen). Statische Config, **ist** in git (ändert sich nach dem
  Setzen nicht mehr, kommt so per `git pull` auf den Server).

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
  awards.py      Auszeichnungen der Finale Edition (10 Kategorien)
  chart.py       Punkteverlauf-Chart als PNG (Finale Edition)
  sync.py        Ergebnis-Abgleich mit openfootball
  bot.py         Telegram-Oberfläche
main.py          Startet den Bot
```
