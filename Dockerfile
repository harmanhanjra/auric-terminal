FROM node:22-alpine AS web-build
WORKDIR /build/web
COPY web/package*.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MARKET_DATA_SOURCE=auto \
    ENABLE_LIVE_TRADING=false \
    ENABLE_AUTO_LIVE_TRADING=false \
    AURIC_EXECUTION_STAGE=paper

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && addgroup --system auric \
    && adduser --system --ingroup auric --home /app auric

COPY server.py engine.py execution_v2.py production_control.py multi_engine.py brain_agent.py kronos_engine.py run_server.py ./
COPY kronos ./kronos
COPY --from=web-build /build/web/dist ./web/dist

RUN chown -R auric:auric /app
USER auric

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
