FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    TRUST_PROXY_HOPS=1

# Hugging Face Spaces runs containers as UID 1000.
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py disease_proteins.json ./
COPY services ./services
COPY static ./static
COPY templates ./templates

USER appuser
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"

# The timeout must exceed LLM_MAX_ATTEMPTS x LLM_TIMEOUT_SECONDS (120 s).
CMD ["sh", "-c", "exec gunicorn app:app --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 150 --access-logfile -"]
