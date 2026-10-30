# ==============================================================================
# Westlandse Bierbrouwerij ZWOL - Dockerfile
# Geoptimaliseerd voor Synology NAS (/volume1/docker/zwol-orders)
# ==============================================================================

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Installeer curl voor de healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Eerst requirements installeren (Docker layer caching)
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Applicatie code kopiëren
COPY . /app/

# Poort vrijgeven
EXPOSE 8503

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl --fail http://localhost:8503/health || exit 1

# Start gunicorn productieserver
CMD ["gunicorn", "--bind", "0.0.0.0:8503", "--workers", "2", "--threads", "4", "app.main:app"]
