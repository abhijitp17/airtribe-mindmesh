FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# tesseract is only used when OCR=tesseract
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*

# Exact versions with hashes (scripts/lock.sh): every build installs the same packages.
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY app ./app
COPY worker.py alembic.ini ./
COPY alembic ./alembic
COPY sql ./sql

RUN useradd --create-home appuser && mkdir -p /data/uploads && chown -R appuser /data
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
