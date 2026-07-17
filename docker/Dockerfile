# SentinelOps-Lite — Python application image
# Build context is the project root:  docker build -f docker/Dockerfile .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY . .

RUN mkdir -p logs

EXPOSE 5000

# Lightweight liveness check (no secrets, no external calls).
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:5000/health'); sys.exit(0)" || exit 1

# Gunicorn serves the Flask `application` object defined in agent_monitor (imported by app).
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", \
     "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "app:application"]
