# WM-26-Tippspiel-Bot – schlankes Image mit uv
FROM python:3.10-slim

# uv-Binary aus dem offiziellen Image holen (schnelle, reproduzierbare Installs)
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1

# Erst nur die Abhängigkeiten installieren (nutzt den Docker-Layer-Cache)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-cache

# Dann der eigentliche Code
COPY . .

# Long-Polling-Bot – kein Port nötig
CMD ["uv", "run", "--frozen", "main.py"]
