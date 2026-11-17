FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 civic \
    && mkdir -p /app/.data /home/civic/.prefect \
    && chown -R civic:civic /app/.data /home/civic/.prefect

COPY pyproject.toml ./
COPY civiclens ./civiclens
ARG PYTHON_EXTRAS=""
RUN pip install --no-cache-dir ".${PYTHON_EXTRAS}"
COPY alembic.ini ./
COPY migrations ./migrations
COPY evaluation/results.json ./evaluation/results.json
USER civic
CMD ["uvicorn", "civiclens.api:app", "--host", "0.0.0.0", "--port", "8000"]
