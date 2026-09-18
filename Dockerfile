# ResidueCheck web app: React build served by FastAPI.
# Keyless by default: with recordings in data/replays it replays recorded agent runs, otherwise it runs on fixed rules.
# Live agents: set NEBIUS_API_KEY (and TAVILY_API_KEY) as secrets; RESIDUECHECK_DAILY_USD caps the spend.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=7860 RESIDUECHECK_ENGINE=auto
RUN useradd -m -u 1000 app
WORKDIR /app
COPY requirements-app.txt ./
RUN pip install --no-cache-dir -r requirements-app.txt
COPY residuecheck/ residuecheck/
COPY data/ data/
COPY --from=web /web/dist web/dist
RUN mkdir -p data/replays && chown -R app:app data/replays
USER app
EXPOSE 7860
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health')"
CMD ["sh", "-c", "uvicorn residuecheck.api:app --host 0.0.0.0 --port ${PORT}"]
