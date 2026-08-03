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

COPY . .
# `pip install -e .` needs the `app/` package directory to already be
# present (setuptools' egg_info step reads it) - it must run after the
# full COPY, not before. This costs some layer-caching efficiency
# (any source change invalidates the dependency-install layer), which is
# an acceptable tradeoff for a project this size versus the complexity of
# a multi-stage copy just to preserve it.
RUN pip install --upgrade pip && pip install -e ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
