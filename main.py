"""Startet den WM-26-Tippspiel-Telegram-Bot.

Starten mit:  uv run main.py
Voraussetzung: TELEGRAM_BOT_TOKEN in der .env-Datei.
"""

from app.bot import run


def main():
    run()


if __name__ == "__main__":
    main()
