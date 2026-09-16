FROM python:3.12-slim
WORKDIR /app

# Install backend deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend sources (all modules imported by server.py)
COPY server.py engine.py multi_engine.py brain_agent.py kronos_engine.py run_server.py ./
COPY kronos ./kronos

# Prebuilt web UI (run `npm run build` inside web/ before docker build).
# If web/dist is missing the backend falls back to index.html.
COPY web/dist ./web/dist

ENV MARKET_DATA_SOURCE=auto \
    ENABLE_LIVE_TRADING=false \
    PYTHONUNBUFFERED=1
EXPOSE 8000

# Fail closed if the gateway stops responding
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
