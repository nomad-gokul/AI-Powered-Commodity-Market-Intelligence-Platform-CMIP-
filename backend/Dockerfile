FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Build context is the repo root (see docker-compose.yml), not backend/ -
# shared/ and ai-service/ are separate installable packages living as
# siblings of backend/ since Pre-Phase 5 (AI Service Extraction), and this
# image needs all three. `pip install -e .` needs each package's own
# directory already present (setuptools' egg_info step reads it) - it must
# run after the full COPY, not before. This costs some layer-caching
# efficiency (any source change invalidates the dependency-install layer),
# an acceptable tradeoff for a project this size versus the complexity of
# a multi-stage copy just to preserve it.
COPY shared ./shared
COPY ai-service ./ai-service
COPY backend ./backend
RUN pip install --upgrade pip \
    && pip install -e ./shared -e ./ai-service -e "./backend[dev]"

# app.main:app / app.worker.settings.WorkerSettings resolve relative to
# this WORKDIR - the CMD below is unchanged from before the package split.
WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
