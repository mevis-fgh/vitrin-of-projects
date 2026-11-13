#!/usr/bin/env bash
# Запуск АИС «Витрина ИТ-проектов» на Linux и macOS.
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "Python 3 не найден. Установите Python 3.10+ (https://www.python.org/downloads/)."
    exit 1
fi

if ! "$PY" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)"; then
    echo "Требуется Python 3.10 или новее. Установлена версия: $("$PY" --version)"
    exit 1
fi

export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-8000}"

echo "АИС «Витрина ИТ-проектов»"
echo "Адрес: http://$HOST:$PORT"
echo "Остановка: Ctrl+C"

(
    sleep 2
    if command -v open >/dev/null 2>&1; then
        open "http://$HOST:$PORT" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "http://$HOST:$PORT" >/dev/null 2>&1 || true
    fi
) &

exec "$PY" app.py
