# Familienkalender – ein Image für Oberfläche und API (ein Cloud-Run-Dienst, gleicher Ursprung, kein CORS)

# 1. Oberfläche bauen
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# 2. API mit der gebauten Oberfläche unter /srv/static
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    KALENDER_STATIC_DIR=/srv/static \
    FORWARDED_ALLOW_IPS=* \
    PORT=8080
WORKDIR /srv
COPY backend/requirements.txt .
RUN pip install --no-compile -r requirements.txt
COPY backend/app ./app
COPY --from=frontend /build/dist ./static

# Kein Root: Cloud Run braucht keine Rechte im Container
RUN useradd --uid 10001 --no-create-home kalender
USER kalender

# --proxy-headers: https und Host aus Cloud Run übernehmen (OAuth-Rücksprungadresse)
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75 --proxy-headers
