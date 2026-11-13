# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Приложение использует только стандартную библиотеку Python,
# поэтому установка зависимостей не требуется.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/data \
    DEMO_MODE=1

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --chown=app:app . .
RUN mkdir -p /data && chown app:app /data

USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1

CMD ["python", "app.py"]
