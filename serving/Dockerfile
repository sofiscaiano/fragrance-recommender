FROM python:3.13-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gfortran \
        libgomp1 \
        libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.8 /uv /uvx /bin/

WORKDIR /app
COPY recommendation-system/pyproject.toml recommendation-system/README.md /app/recommendation-system/
COPY recommendation-system/fragrantica_rec /app/recommendation-system/fragrantica_rec
COPY serving/pyproject.toml serving/uv.lock /app/serving/
COPY serving/src /app/serving/src

WORKDIR /app/serving
RUN uv sync --frozen --no-dev

ENV PATH="/app/serving/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    FRAGRANTICA_MODEL=/models/serving.joblib \
    FRAGRANTICA_DATA=/data

EXPOSE 8000
CMD ["uvicorn", "fragrantica_serving.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
