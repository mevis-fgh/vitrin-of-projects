"""Работа с базой данных: схема, миграции, сессии, аудит и уведомления."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta

from core import (
    ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_USERNAME, DB_PATH, DEMO_MODE,
    SESSION_TTL_HOURS, new_token, now,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','company','student')),
    full_name TEXT NOT NULL,
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    institute TEXT DEFAULT '',
    program TEXT DEFAULT '',
    course TEXT DEFAULT '',
    group_name TEXT DEFAULT '',
    skills TEXT DEFAULT '',
    bio TEXT DEFAULT '',
    github TEXT DEFAULT '',
    links TEXT DEFAULT '',
    blocked INTEGER NOT NULL DEFAULT 0,
    consent_at TEXT DEFAULT '',
    last_login TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER UNIQUE NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT DEFAULT '',
    description TEXT DEFAULT '',
    industry TEXT DEFAULT 'ИТ',
    website TEXT DEFAULT '',
    contacts TEXT DEFAULT '',
    logo TEXT DEFAULT '',
    approved INTEGER NOT NULL DEFAULT 0,
    moderation_note TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    short_description TEXT NOT NULL,
    description TEXT NOT NULL,
    direction TEXT NOT NULL,
    technologies TEXT DEFAULT '',
    difficulty TEXT DEFAULT 'Средний',
    participation_format TEXT DEFAULT 'Командный',
    work_format TEXT DEFAULT 'Дистанционный',
    team_size INTEGER DEFAULT 4,
    deadline TEXT DEFAULT '',
    reward_type TEXT DEFAULT 'Образовательный',
    reward_amount INTEGER DEFAULT 0,
    prize_fund INTEGER DEFAULT 0,
    reward_details TEXT DEFAULT '',
    requirements TEXT DEFAULT '',
    evaluation TEXT DEFAULT '',
    rights_mode TEXT DEFAULT 'Результаты остаются у авторов',
    nda_required INTEGER DEFAULT 0,
    internship INTEGER DEFAULT 0,
    course INTEGER DEFAULT 0,
    status TEXT DEFAULT 'На модерации',
    moderation_note TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT DEFAULT '',
    FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    message TEXT DEFAULT '',
    portfolio_url TEXT DEFAULT '',
    github_url TEXT DEFAULT '',
    resume_url TEXT DEFAULT '',
    status TEXT DEFAULT 'Подана',
    project_status TEXT DEFAULT 'Заявка',
    result_url TEXT DEFAULT '',
    result_note TEXT DEFAULT '',
    result_file_id INTEGER,
    score INTEGER,
    place TEXT DEFAULT '',
    review TEXT DEFAULT '',
    payment_status TEXT DEFAULT 'Не предусмотрена',
    invited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT DEFAULT '',
    UNIQUE(case_id, student_id),
    FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS student_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    short_description TEXT NOT NULL,
    description TEXT NOT NULL,
    direction TEXT NOT NULL,
    technologies TEXT DEFAULT '',
    repo_url TEXT DEFAULT '',
    demo_url TEXT DEFAULT '',
    presentation_url TEXT DEFAULT '',
    needs TEXT DEFAULT '',
    status TEXT DEFAULT 'Опубликован',
    created_at TEXT NOT NULL,
    FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    case_id INTEGER NOT NULL,
    UNIQUE(student_id, case_id),
    FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    link TEXT DEFAULT '',
    is_read INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS sessions (
    sid TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    csrf TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    leader_user_id INTEGER,
    mentor TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS team_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT DEFAULT '',
    UNIQUE(team_id, user_id),
    FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    due_date TEXT DEFAULT '',
    status TEXT DEFAULT 'Ожидается',
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    case_id INTEGER,
    application_id INTEGER,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    size INTEGER DEFAULT 0,
    content_type TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    case_id INTEGER,
    message TEXT DEFAULT '',
    status TEXT DEFAULT 'Отправлено',
    created_at TEXT NOT NULL,
    FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    object_type TEXT DEFAULT '',
    object_id INTEGER,
    details TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
CREATE INDEX IF NOT EXISTS idx_cases_company ON cases(company_id);
CREATE INDEX IF NOT EXISTS idx_apps_case ON applications(case_id);
CREATE INDEX IF NOT EXISTS idx_apps_student ON applications(student_id);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_sessions_exp ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_comments_case ON comments(case_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
"""

# Колонки, добавленные к схеме после первых версий проекта
MIGRATIONS = {
    "users": [
        ("links", "TEXT DEFAULT ''"),
        ("blocked", "INTEGER NOT NULL DEFAULT 0"),
        ("consent_at", "TEXT DEFAULT ''"),
        ("last_login", "TEXT DEFAULT ''"),
    ],
    "companies": [
        ("logo", "TEXT DEFAULT ''"),
        ("moderation_note", "TEXT DEFAULT ''"),
        ("created_at", "TEXT DEFAULT ''"),
    ],
    "cases": [
        ("internship", "INTEGER DEFAULT 0"),
        ("course", "INTEGER DEFAULT 0"),
        ("moderation_note", "TEXT DEFAULT ''"),
        ("updated_at", "TEXT DEFAULT ''"),
    ],
    "applications": [
        ("github_url", "TEXT DEFAULT ''"),
        ("resume_url", "TEXT DEFAULT ''"),
        ("result_note", "TEXT DEFAULT ''"),
        ("result_file_id", "INTEGER"),
        ("invited", "INTEGER NOT NULL DEFAULT 0"),
        ("updated_at", "TEXT DEFAULT ''"),
    ],
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
        return secrets.compare_digest(hash_password(password, salt), stored)
    except Exception:
        return False


def _columns(conn, table: str) -> set:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _apply_migrations(conn) -> None:
    for table, columns in MIGRATIONS.items():
        existing = _columns(conn, table)
        for name, ddl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


# --------------------------------------------------------------------------
# Сессии и CSRF
# --------------------------------------------------------------------------
def create_session(user_id: int):
    sid, csrf = new_token(), new_token()
    expires = (datetime.now() + timedelta(hours=SESSION_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    conn = connect()
    conn.execute(
        "INSERT INTO sessions(sid,user_id,csrf,created_at,expires_at) VALUES (?,?,?,?,?)",
        (sid, user_id, csrf, now(), expires),
    )
    conn.commit()
    conn.close()
    return sid, csrf


def load_session(sid: str):
    """Возвращает (session, user) или (None, None)."""
    if not sid:
        return None, None
    conn = connect()
    session = conn.execute("SELECT * FROM sessions WHERE sid=?", (sid,)).fetchone()
    user = None
    if session:
        if session["expires_at"] < now():
            conn.execute("DELETE FROM sessions WHERE sid=?", (sid,))
            conn.commit()
            session = None
        else:
            user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    if user is not None and user["blocked"]:
        delete_session(sid)
        return None, None
    return session, user


def delete_session(sid: str) -> None:
    if not sid:
        return
    conn = connect()
    conn.execute("DELETE FROM sessions WHERE sid=?", (sid,))
    conn.commit()
    conn.close()


def cleanup_sessions() -> None:
    conn = connect()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Аудит и уведомления
# --------------------------------------------------------------------------
def audit(conn, user_id, action: str, object_type: str = "", object_id=None, details: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_log(user_id,action,object_type,object_id,details,created_at) VALUES (?,?,?,?,?,?)",
        (user_id, action, object_type, object_id, (details or "")[:500], now()),
    )


def notify(conn, user_id, text: str, link: str = "") -> None:
    if not user_id:
        return
    conn.execute(
        "INSERT INTO notifications(user_id,text,link,created_at) VALUES (?,?,?,?)",
        (user_id, text[:500], link[:300], now()),
    )


def notify_admins(conn, text: str, link: str = "") -> None:
    for row in conn.execute("SELECT id FROM users WHERE role='admin'").fetchall():
        notify(conn, row["id"], text, link)


# --------------------------------------------------------------------------
# Инициализация и демонстрационные данные
# --------------------------------------------------------------------------
def init_db() -> None:
    conn = connect()
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    _apply_migrations(conn)
    conn.commit()

    users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if users_count == 0:
        if DEMO_MODE:
            _seed_demo(conn)
        else:
            _seed_admin(conn)
    else:
        _ensure_admin(conn)
    conn.commit()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
    conn.commit()
    conn.close()


def _seed_admin(conn) -> None:
    conn.execute(
        "INSERT INTO users(username,password,role,full_name,email,created_at) VALUES (?,?,?,?,?,?)",
        (ADMIN_USERNAME, hash_password(ADMIN_PASSWORD), "admin", "Администратор системы", ADMIN_EMAIL, now()),
    )


def _ensure_admin(conn) -> None:
    row = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if not row:
        _seed_admin(conn)


def _seed_demo(conn) -> None:
    """Демонстрационный набор данных: компании, кейсы, заявки, команды, отзывы."""
    users = [
        (ADMIN_USERNAME, hash_password(ADMIN_PASSWORD), "admin", "Администратор УУНиТ", ADMIN_EMAIL, "", "", "", "", "", "", "", "", "", ""),
        ("company", hash_password("Company123!"), "company", "Айгуль Хайруллина", "a.hairullina@digital-solutions.ru", "+7 347 200-10-10", "", "", "", "", "", "", "", "", ""),
        ("company2", hash_password("Company123!"), "company", "Марат Сафин", "m.safin@technopolis.ru", "+7 347 200-20-20", "", "", "", "", "", "", "", "", ""),
        ("company3", hash_password("Company123!"), "company", "Ольга Дёмина", "o.demina@fintech-alliance.ru", "+7 495 100-30-30", "", "", "", "", "", "", "", "", ""),
        ("student01", hash_password("Student123!"), "student", "Иванов Иван Иванович", "student01@uust.ru", "+7 917 000-00-01", "ИИМРТ", "09.03.04 Программная инженерия", "2", "ТОП-202Б", "Python, FastAPI, SQL, Docker", "Интересуюсь backend-разработкой и ML. Ищу стажировку.", "https://github.com/example", "https://t.me/example"),
        ("student02", hash_password("Student123!"), "student", "Петрова Анна Сергеевна", "student02@uust.ru", "+7 917 000-00-02", "ИИМРТ", "09.03.03 Прикладная информатика", "3", "ПИ-301Б", "JavaScript, React, TypeScript, Figma", "Frontend-разработка и UX/UI.", "https://github.com/example2", ""),
        ("student03", hash_password("Student123!"), "student", "Сидоров Кирилл Андреевич", "student03@uust.ru", "+7 917 000-00-03", "ИИМРТ", "01.03.02 Прикладная математика и информатика", "1", "ПМИ-101Б", "Python, PyTorch, Pandas, SQL", "ML-инженер, участвую в хакатонах.", "https://github.com/example3", ""),
        ("student04", hash_password("Student123!"), "student", "Кузнецова Мария Олеговна", "student04@uust.ru", "+7 917 000-00-04", "ИЭУИС", "38.03.05 Бизнес-информатика", "4", "БИ-401Б", "SQL, Power BI, тестирование, аналитика", "Бизнес-аналитик, люблю данные и визуализацию.", "", ""),
    ]
    prepared_users = []
    for user in users:
        fields = tuple(user)[:14]
        fields += ("",) * (14 - len(fields))
        prepared_users.append(fields + (now(),))
    conn.executemany(
        """INSERT INTO users(username,password,role,full_name,email,phone,institute,program,course,
           group_name,skills,bio,github,links,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        prepared_users,
    )

    ids = {row["username"]: row["id"] for row in conn.execute("SELECT id,username FROM users")}
    companies = [
        (ids["company"], "ООО «Цифровые решения»", "Цифровые решения",
         "ИТ-компания, разрабатывающая корпоративные цифровые продукты и аналитические сервисы. "
         "Работаем со студентами с 2021 года: стажировки, наставничество, трудоустройство.",
         "ИТ / разработка ПО", "https://example.ru", "projects@example.ru", 1, ""),
        (ids["company2"], "АО «ТехноПолис»", "ТехноПолис",
         "Системный интегратор: мобильная разработка, инфраструктура, информационная безопасность.",
         "Интеграция и ИБ", "https://technopolis.example", "hr@technopolis.example", 1, ""),
        (ids["company3"], "ООО «ФинТех Альянс»", "ФинТех Альянс",
         "Финтех-стартап: платёжные сервисы и скоринг на данных.",
         "Финтех", "https://fintech-alliance.example", "team@fintech-alliance.example", 0,
         "Ожидает проверки реквизитов"),
    ]
    for owner_id, name, short, desc, industry, site, contacts, approved, note in companies:
        conn.execute(
            """INSERT INTO companies(owner_user_id,name,short_name,description,industry,website,
               contacts,approved,moderation_note,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (owner_id, name, short, desc, industry, site, contacts, approved, note, now()),
        )
    cid1 = conn.execute("SELECT id FROM companies WHERE name LIKE 'ООО «Цифровые решения»'").fetchone()["id"]
    cid2 = conn.execute("SELECT id FROM companies WHERE name LIKE 'АО «ТехноПолис»'").fetchone()["id"]
    cid3 = conn.execute("SELECT id FROM companies WHERE name LIKE 'ООО «ФинТех Альянс»'").fetchone()["id"]

    cases = [
        (cid1, "Сервис интеллектуального поиска по базе знаний",
         "Разработать веб-сервис семантического поиска по внутренним документам.",
         "Необходимо реализовать прототип системы поиска по документам с использованием эмбеддингов, "
         "API и удобного интерфейса. Требуется продемонстрировать архитектуру, поиск, ранжирование и "
         "базовую аналитику (сколько запросов, средняя релевантность, топ-документы).",
         "Искусственный интеллект", "Python, FastAPI, PostgreSQL, embeddings", "Высокий",
         "Командный", "Дистанционный", 4, "2026-12-15", "Конкурсный", 0, 100000,
         "Призовой фонд 100 000 ₽: 50/30/20 тыс. ₽ за первые три места. Победители получают приглашение на стажировку.",
         "Python, REST API, базы данных, Git, базовые знания NLP",
         "Качество поиска, архитектура, читаемость кода, документация, презентация решения",
         "Простая неисключительная лицензия компании", 0, 1, 0, "Опубликован"),
        (cid1, "Мобильный кабинет студента",
         "Создать MVP мобильного приложения для отслеживания учебных задач.",
         "Нужно создать кроссплатформенное приложение с авторизацией, календарём задач, "
         "уведомлениями и демонстрационными данными. Важны аккуратный UI и понятная навигация.",
         "Мобильная разработка", "Flutter, Dart, REST API", "Средний", "Командный",
         "Смешанный", 3, "2026-11-30", "С вознаграждением", 50000, 0,
         "50 000 ₽ за принятый MVP, выплата после приёмки результата.",
         "Flutter или React Native, Git, базовый UI/UX",
         "Работоспособность, UX, качество кода, соблюдение требований",
         "Результаты остаются у авторов", 0, 0, 2, "Опубликован"),
        (cid2, "Дашборд кибербезопасности",
         "Собрать интерактивный дашборд событий ИБ на тестовых данных.",
         "Образовательный кейс: спроектировать интерфейс дашборда, обработать набор событий и "
         "реализовать основные визуализации и фильтры по типам инцидентов и подразделениям.",
         "Информационная безопасность", "Python, SQL, JavaScript, BI", "Средний",
         "Индивидуальный", "Дистанционный", 1, "2026-12-01", "Образовательный", 0, 0,
         "Сертификат и отзыв компании. Лучшие участники получат приглашение на стажировку.",
         "SQL, основы ИБ, визуализация данных", "Полнота, наглядность, корректность метрик",
         "Результаты остаются у авторов", 0, 1, 0, "Опубликован"),
        (cid2, "Игровой тренажёр для онбординга",
         "Разработать мини-игру, объясняющую процессы компании новым сотрудникам.",
         "Нужен браузерный тренажёр на 3–4 сценария: знакомство с отделами, безопасность, "
         "внутренние сервисы. Формат — небольшой квест с прогрессом и обратной связью.",
         "Разработка игр", "TypeScript, Phaser, HTML5", "Начальный", "Командный",
         "Дистанционный", 4, "2026-10-20", "Иное вознаграждение", 0, 0,
         "Оплачиваемая стажировка в продуктовой команде и подарки.",
         "TypeScript, базовые знания HTML5 Canvas", "Играбельность, качество кода, оформление",
         "Передача исключительного права по отдельному соглашению", 1, 1, 0, "Опубликован"),
        (cid1, "Аналитика взаимодействия с вузами",
         "Подготовить аналитический отчёт по заявкам компаний за последний год.",
         "Задача для бизнес-аналитика: собрать метрики по воронке (кейс → заявка → приём → "
         "завершение), построить дашборд и предложить выводы для HR-службы.",
         "Бизнес-анализ", "SQL, Excel, Power BI", "Начальный", "Индивидуальный",
         "Дистанционный", 1, "2026-11-10", "Образовательный", 0, 0,
         "Сертификат, отзыв, приглашение на стажировку в отдел аналитики.",
         "Excel, SQL базово", "Качество выводов, структура отчёта", "Результаты остаются у авторов", 0, 0, 3, "Опубликован"),
        (cid2, "Мобильный кабинет студента — 2 поток",
         "Доработать MVP мобильного приложения по итогам первого этапа.",
         "Требуется доработать существующий прототип: офлайн-режим, push-уведомления и "
         "тёмная тема. Код первого этапа доступен в репозитории компании.",
         "Мобильная разработка", "Flutter, Dart, Firebase", "Средний", "Командный",
         "Дистанционный", 3, "2026-12-20", "С вознаграждением", 60000, 0,
         "60 000 ₽ за принятый результат.", "Flutter, REST/Firebase", "Функциональность, качество кода",
         "Результаты остаются у авторов", 0, 0, 0, "На модерации"),
        (cid3, "Скоринг заявок для платёжного сервиса",
         "Исследовать признаки и собрать прототип модели скоринга.",
         "Задача с NDA: данные предоставляются после подписания соглашения. Нужно исследовать "
         "признаки, собрать прототип модели и оценить качество на исторических данных.",
         "Машинное обучение", "Python, scikit-learn, Pandas", "Высокий", "Индивидуальный",
         "Дистанционный", 1, "2026-12-05", "С вознаграждением", 80000, 0,
         "80 000 ₽ за принятую модель и отчёт.", "ML, статистика, Python", "Качество модели, обоснованность",
         "Передача исключительного права по отдельному соглашению", 1, 0, 0, "На модерации"),
        (cid1, "Чат-бот поддержки студентов",
         "Разработать бота с ответами на типовые вопросы студентов.",
         "Бот отвечает на частые вопросы, показывает ссылки на сервисы и передаёт сложные "
         "обращения оператору. Нужны база знаний и метрики качества ответов.",
         "Backend", "Python, Telegram Bot API, SQLite", "Начальный", "Индивидуальный",
         "Дистанционный", 1, "2026-09-30", "Образовательный", 0, 0,
         "Сертификат и отзыв компании.", "Python, базовые знания SQL", "Работоспособность, качество ответов",
         "Результаты остаются у авторов", 0, 0, 0, "Завершён"),
    ]
    for case in cases:
        conn.execute(
            """INSERT INTO cases(company_id,title,short_description,description,direction,technologies,
               difficulty,participation_format,work_format,team_size,deadline,reward_type,reward_amount,
               prize_fund,reward_details,requirements,evaluation,rights_mode,nda_required,internship,
               course,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            tuple(case) + (now(), now()),
        )
    case_ids = [row["id"] for row in conn.execute("SELECT id FROM cases ORDER BY id")]

    applications = [
        (case_ids[0], ids["student01"], "Хочу участвовать: есть опыт с FastAPI и эмбеддингами, делал поиск по документам на учебном проекте.",
         "https://github.com/example", "https://github.com/example/search", "",
         "Принята", "Завершён", "https://github.com/example/search", "Прототип поиска и отчёт по метрикам.",
         None, 92, "1 место", "Отличная работа: быстрый поиск, аккуратная архитектура и понятная документация. Рекомендуем к стажировке.",
         "Произведена", now()),
        (case_ids[1], ids["student02"], "Frontend-разработчик, умею Flutter и Figma, делала мобильные прототипы.",
         "https://github.com/example2", "", "", "Принята", "Выполняется", "", "",
         None, None, "", "", "Не предусмотрена", now()),
        (case_ids[1], ids["student04"], "Могу взять на себя аналитику и тестирование сценариев.",
         "", "", "", "Принята", "Выполняется", "", "", None, None, "", "", "Не предусмотрена", now()),
        (case_ids[2], ids["student03"], "Интересна визуализация и работа с событиями ИБ.",
         "https://github.com/example3", "", "", "Подана", "Заявка", "", "", None, None, "", "", "Не предусмотрена", now()),
        (case_ids[3], ids["student02"], "Готова сделать квест, есть опыт в Phaser.",
         "", "", "", "Собеседование", "Отбор", "", "", None, None, "", "", "Не предусмотрена", now()),
        (case_ids[7], ids["student01"], "Сделаю бота поддержки на Python.",
         "", "", "", "Принята", "Завершён", "https://github.com/example/campusbot", "Бот запущен в тестовом режиме.",
         None, 88, "2 место", "Хорошая работа, не хватило аналитики по метрикам качества.", "Подтверждена", now()),
        (case_ids[0], ids["student03"], "Могу помочь с ML-частью и оценкой качества поиска.",
         "", "", "", "Отклонена", "Заявка", "", "", None, None, "", "", "Не предусмотрена", now()),
    ]
    for app_row in applications:
        conn.execute(
            """INSERT INTO applications(case_id,student_id,message,portfolio_url,github_url,resume_url,
               status,project_status,result_url,result_note,result_file_id,score,place,review,
               payment_status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            app_row + (now(),),
        )

    # Команда для второго кейса (формирование команд компанией)
    conn.execute(
        "INSERT INTO teams(case_id,name,leader_user_id,mentor,created_at) VALUES (?,?,?,?,?)",
        (case_ids[1], "Mobile Squad", ids["student02"], "Айгуль Хайруллина (продуктовый дизайн)", now()),
    )
    team_id = conn.execute("SELECT id FROM teams WHERE case_id=?", (case_ids[1],)).fetchone()["id"]
    for user_id, role in ((ids["student02"], "Team Lead"), (ids["student04"], "Analyst")):
        conn.execute("INSERT INTO team_members(team_id,user_id,role) VALUES (?,?,?)", (team_id, user_id, role))

    # Контрольные точки проекта
    stages = [
        (case_ids[1], "Анализ задачи", "Согласовать сценарии и список экранов", "2026-10-15", "Выполнена"),
        (case_ids[1], "Проектирование", "Макеты в Figma, схема навигации", "2026-10-25", "Выполняется"),
        (case_ids[1], "Разработка MVP", "Авторизация, календарь задач, уведомления", "2026-11-15", "Ожидается"),
    ]
    for stage in stages:
        conn.execute(
            "INSERT INTO stages(case_id,title,description,due_date,status,created_at) VALUES (?,?,?,?,?,?)",
            tuple(stage) + (now(),),
        )

    # Комментарии рабочей страницы
    comments = [
        (case_ids[1], ids["company"], "Коллеги, привет! Добавила макеты в Figma, ссылка в задаче. Вопросы — сюда."),
        (case_ids[1], ids["student02"], "Спасибо! Начали с авторизации, к пятнице покажем первый экран."),
        (case_ids[0], ids["student01"], "Отчёт по метрикам приложен, прошу посмотреть раздел с ранжированием."),
    ]
    for case_id, user_id, text in comments:
        conn.execute(
            "INSERT INTO comments(case_id,user_id,text,created_at) VALUES (?,?,?,?)",
            (case_id, user_id, text, now()),
        )

    # Собственные проекты студентов
    projects = [
        (ids["student01"], "CampusBot", "Telegram-бот для навигации по сервисам университета.",
         "Бот отвечает на типовые вопросы студентов, содержит справочник подразделений и быстрые ссылки.",
         "Backend", "Python, Telegram Bot API, SQLite", "https://github.com/example/campusbot", "", "",
         "Ищу наставника; открыт к стажировке"),
        (ids["student02"], "StudyFlow", "Прототип интерфейса планировщика учебных задач.",
         "Веб-приложение с Kanban-доской, календарём и приоритизацией задач.",
         "Frontend", "React, TypeScript, Figma", "https://github.com/example2/studyflow",
         "https://example.com", "", "Ищу компанию / партнёра"),
        (ids["student03"], "ML-детектор аномалий", "Учебный проект по поиску аномалий в логах.",
         "Модель на Isolation Forest, сравнение с z-score, отчёт по метрикам на открытом датасете.",
         "Машинное обучение", "Python, scikit-learn, Pandas", "https://github.com/example3/anomaly", "", "",
         "Ищу команду для хакатона"),
    ]
    for project in projects:
        conn.execute(
            """INSERT INTO student_projects(student_id,title,short_description,description,direction,
               technologies,repo_url,demo_url,presentation_url,needs,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            tuple(project) + ("Опубликован", now()),
        )

    conn.execute("INSERT INTO favorites(student_id,case_id) VALUES (?,?)", (ids["student01"], case_ids[2]))
    conn.execute("INSERT INTO favorites(student_id,case_id) VALUES (?,?)", (ids["student03"], case_ids[0]))

    conn.execute(
        """INSERT INTO invitations(company_id,student_id,case_id,message,status,created_at)
           VALUES (?,?,?,?,?,?)""",
        (cid1, ids["student03"], case_ids[0],
         "Приглашаем в команду по кейсу «Сервис интеллектуального поиска» — нужен ML-инженер.", "Отправлено", now()),
    )

    notify(conn, ids["company"], "Новая заявка от Петрова Анна Сергеевна на кейс «Мобильный кабинет студента»", "/dashboard")
    notify(conn, ids["company"], "Новая заявка от Кузнецова Мария Олеговна на кейс «Мобильный кабинет студента»", "/dashboard")
    notify(conn, ids["student01"], "Компания приняла вашу заявку по кейсу «Чат-бот поддержки студентов»", "/dashboard")
    notify(conn, ids["student02"], "Обновлён статус по кейсу «Мобильный кабинет студента»: Выполняется", "/dashboard")
    notify(conn, ids["student03"], "Вам отправлено приглашение в команду по кейсу «Сервис интеллектуального поиска»", "/notifications")
    notify_admins(conn, "Новый кейс «Скоринг заявок для платёжного сервиса» ожидает модерации", "/dashboard")
    notify_admins(conn, "Компания «ФинТех Альянс» ожидает проверки", "/dashboard")

    audit(conn, ids["admin"], "seed", "system", None, "Демонстрационные данные загружены")


def reset_db() -> None:
    """Полный сброс базы (используется флагом --reset-demo)."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = DB_PATH.with_name(DB_PATH.name + suffix)
        if path.exists():
            path.unlink()
    init_db()
