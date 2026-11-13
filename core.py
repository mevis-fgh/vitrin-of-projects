"""Конфигурация, утилиты и безопасность АИС «Витрина ИТ-проектов».

Модуль не зависит от базы данных: только настройки, форматирование,
разбор запросов, ограничение попыток входа и работа с загружаемыми файлами.
"""
from __future__ import annotations

import email.parser
import email.policy
import html
import os
import re
import secrets
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------
# Конфигурация (всё переопределяется переменными окружения)
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


def _env_path(name: str, default: Path) -> Path:
    raw = (os.environ.get(name) or "").strip()
    return Path(raw).expanduser().resolve() if raw else default


DATA_DIR = _env_path("DATA_DIR", BASE_DIR)
DB_PATH = _env_path("DB_PATH", DATA_DIR / "data.sqlite3")
UPLOAD_DIR = _env_path("UPLOAD_DIR", DATA_DIR / "uploads")
STATIC_DIR = BASE_DIR / "static"

for _directory in (DATA_DIR, UPLOAD_DIR):
    try:
        _directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - защита от read-only ФС
        print(f"[warn] Не удалось создать каталог {_directory}: {exc}")

HOST = (os.environ.get("HOST") or "127.0.0.1").strip()
PORT = int(os.environ.get("PORT") or "8000")
DEMO_MODE = _env_bool("DEMO_MODE", True)
REGISTRATION_OPEN = _env_bool("REGISTRATION_OPEN", True)
COOKIE_SECURE = _env_bool("COOKIE_SECURE", False)
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS") or "12")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB") or "15")
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_BODY_BYTES = MAX_UPLOAD_BYTES + 2 * 1024 * 1024
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME") or "admin"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or "Admin12345!"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL") or "admin@uust.ru"
APP_VERSION = "1.0.0"

# Справочники (расширяются без изменения структуры БД)
ROLES = {"admin": "Администратор", "company": "Компания", "student": "Студент"}
DIRECTIONS = [
    "Backend", "Frontend", "Fullstack", "Мобильная разработка", "Искусственный интеллект",
    "Машинное обучение", "Data Science", "Big Data", "DevOps", "Информационная безопасность",
    "Робототехника", "Компьютерное зрение", "Системное программирование", "Базы данных",
    "Тестирование", "UX/UI", "Бизнес-анализ", "Системный анализ", "Разработка игр", "AR/VR",
    "IoT", "Автоматизация", "Облачные технологии", "Другое",
]
DIFFICULTIES = ["Начальный", "Средний", "Высокий"]
PARTICIPATION = ["Индивидуальный", "Командный"]
WORK_FORMATS = ["Дистанционный", "Очный", "Смешанный"]
REWARD_TYPES = ["Образовательный", "Конкурсный", "С вознаграждением", "Иное вознаграждение"]
CASE_STATUSES = ["Черновик", "На модерации", "Опубликован", "Отклонён", "Скрыт", "Завершён"]
APPLICATION_STATUSES = ["Подана", "Собеседование", "Принята", "Отклонена"]
PROJECT_STATUSES = [
    "Заявка", "Отбор", "Принята", "Выполняется", "Представлен результат",
    "На проверке", "Требуется доработка", "Выполнен", "Завершён",
]
PAYMENT_STATUSES = ["Не предусмотрена", "Ожидается", "Подтверждена", "Произведена"]
TEAM_ROLES = [
    "Team Lead", "Backend Developer", "Frontend Developer", "Mobile Developer",
    "Data Scientist", "ML Engineer", "DevOps Engineer", "QA Engineer", "Designer",
    "Analyst", "Project Manager", "Иная роль",
]
STAGE_TITLES = [
    "Анализ задачи", "Проектирование", "Создание прототипа", "Разработка MVP",
    "Тестирование", "Финальная версия", "Защита проекта",
]
ALLOWED_UPLOADS = {
    ".pdf", ".zip", ".7z", ".rar", ".png", ".jpg", ".jpeg", ".gif", ".txt", ".md",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".mp4", ".webm", ".ipynb",
    ".py", ".js", ".ts", ".html", ".css", ".sql", ".json", ".csv",
}


# --------------------------------------------------------------------------
# Ошибки и переходы
# --------------------------------------------------------------------------
class HttpError(Exception):
    """Ожидаемая ошибка, которую нужно показать пользователю."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Redirect(Exception):
    """Перенаправление после успешной обработки формы."""

    def __init__(self, url: str):
        super().__init__(url)
        self.url = url


# --------------------------------------------------------------------------
# Форматирование
# --------------------------------------------------------------------------
def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def money(value) -> str:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return "—"
    if number <= 0:
        return "—"
    return f"{number:,}".replace(",", " ") + " ₽"


def date_ru(value) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue
    return text


def clip(text, limit: int = 180) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def safe_url(value) -> str:
    """Пропускает только http(s)-ссылки, чтобы исключить javascript:-URL."""
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.match(r"^https?://", text, re.IGNORECASE):
        return ""
    if len(text) > 500 or any(ch in text for ch in "\r\n\t \"'<>"):
        return ""
    return text


def human_size(size) -> str:
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "—"
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return "—"


def valid_email(value) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-zА-Яа-я]{2,}", str(value or "").strip()))


def password_problem(password: str) -> str | None:
    if len(password) < 8:
        return "Пароль должен содержать не менее 8 символов."
    if not re.search(r"[A-Za-zА-Яа-я]", password) or not re.search(r"\d", password):
        return "Пароль должен содержать буквы и цифры."
    if password.strip() != password:
        return "Пароль не должен начинаться или заканчиваться пробелом."
    return None


def int_or(value, default=0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def opt_int(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Разбор входящих запросов
# --------------------------------------------------------------------------
def parse_multipart(content_type: str, body: bytes):
    collected: dict[str, list[str]] = {}
    files: list[dict] = []
    envelope = (
        b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\n"
        b"MIME-Version: 1.0\r\n\r\n" + body
    )
    try:
        message = email.parser.BytesParser(policy=email.policy.default).parsebytes(envelope)
    except Exception:
        return {}, files
    if not message.is_multipart():
        return {}, files
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename:
            files.append({
                "field": str(name),
                "filename": str(filename),
                "data": payload,
                "content_type": part.get_content_type(),
            })
        else:
            collected.setdefault(str(name), []).append(payload.decode("utf-8", "replace"))
    return {key: ",".join(values) for key, values in collected.items()}, files


def parse_request(handler):
    """Возвращает (поля формы, загруженные файлы).

    Повторяющиеся поля (например, набор чекбоксов) объединяются через запятую.
    """
    length_raw = handler.headers.get("Content-Length") or "0"
    try:
        length = int(length_raw)
    except ValueError:
        raise HttpError(400, "Некорректный заголовок Content-Length.")
    if length > MAX_BODY_BYTES:
        raise HttpError(413, f"Слишком большой запрос. Максимальный размер файла — {MAX_UPLOAD_MB} МБ.")
    body = handler.rfile.read(length) if length > 0 else b""
    content_type = handler.headers.get("Content-Type") or ""
    if content_type.lower().startswith("multipart/form-data"):
        return parse_multipart(content_type, body)
    fields: dict[str, str] = {}
    try:
        parsed = urllib.parse.parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    except Exception:
        parsed = {}
    for key, values in parsed.items():
        fields[key] = ",".join(values)
    return fields, []


def cookie_value(handler, name: str) -> str:
    raw = handler.headers.get("Cookie") or ""
    for chunk in raw.split(";"):
        key, _, value = chunk.strip().partition("=")
        if key == name:
            return value
    return ""


def session_cookie(sid: str) -> str:
    parts = [f"sid={sid}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={SESSION_TTL_HOURS * 3600}"]
    if COOKIE_SECURE:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie() -> str:
    parts = ["sid=", "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
    if COOKIE_SECURE:
        parts.append("Secure")
    return "; ".join(parts)


def client_ip(handler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return handler.client_address[0] if handler.client_address else "unknown"


# --------------------------------------------------------------------------
# Ограничение попыток авторизации (защита от подбора пароля)
# --------------------------------------------------------------------------
_LOGIN_LOCK = threading.Lock()
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_WINDOW = 15 * 60
_LOGIN_MAX_FAILS = 10


def login_retry_after(key: str) -> int:
    """Сколько секунд осталось до разблокировки (0 — можно пробовать)."""
    with _LOGIN_LOCK:
        stamps = [t for t in _LOGIN_ATTEMPTS.get(key, []) if time.time() - t < _LOGIN_WINDOW]
        _LOGIN_ATTEMPTS[key] = stamps
        if len(stamps) < _LOGIN_MAX_FAILS:
            return 0
        return max(1, int(_LOGIN_WINDOW - (time.time() - stamps[0])))


def note_login_failure(key: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.setdefault(key, []).append(time.time())


def note_login_success(key: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop(key, None)


# --------------------------------------------------------------------------
# Загружаемые файлы
# --------------------------------------------------------------------------
def save_upload(file_info: dict) -> dict:
    """Проверяет и сохраняет файл под случайным именем. Возвращает метаданные."""
    original = Path(str(file_info.get("filename") or "")).name
    suffix = Path(original).suffix.lower()
    if not original:
        raise HttpError(400, "Не указано имя файла.")
    if suffix not in ALLOWED_UPLOADS:
        raise HttpError(400, f"Недопустимый тип файла «{suffix or 'без расширения'}».")
    data = file_info.get("data") or b""
    if not data:
        raise HttpError(400, "Файл пустой.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HttpError(413, f"Файл больше {MAX_UPLOAD_MB} МБ.")
    stored = f"{secrets.token_hex(16)}{suffix}"
    (UPLOAD_DIR / stored).write_bytes(data)
    return {
        "original_name": original[:200],
        "stored_name": stored,
        "size": len(data),
        "content_type": str(file_info.get("content_type") or "application/octet-stream")[:120],
    }


def new_token() -> str:
    return secrets.token_urlsafe(32)
