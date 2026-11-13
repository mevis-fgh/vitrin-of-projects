"""HTML-представления АИС «Витрина ИТ-проектов» (публичная часть и авторизация)."""
from __future__ import annotations

import core
from core import (
    APPLICATION_STATUSES, CASE_STATUSES, DEMO_MODE, DIRECTIONS, DIFFICULTIES,
    MAX_UPLOAD_MB, PARTICIPATION, PAYMENT_STATUSES, PROJECT_STATUSES,
    REGISTRATION_OPEN, REWARD_TYPES, ROLES, STAGE_TITLES, TEAM_ROLES, WORK_FORMATS,
    HttpError, Redirect, clip, date_ru, esc, human_size, money, now, password_problem,
    safe_url, valid_email,
)
import db


# --------------------------------------------------------------------------
# Контекст запроса и вспомогательные функции
# --------------------------------------------------------------------------
class Ctx:
    __slots__ = ("user", "session", "params", "form", "files", "sid", "ip")

    def __init__(self, user, session, params, form, files, sid="", ip=""):
        self.user = user
        self.session = session
        self.params = params or {}
        self.form = form or {}
        self.files = files or []
        self.sid = sid or ""
        self.ip = ip or ""

    @property
    def csrf(self) -> str:
        return self.session["csrf"] if self.session else ""

    @property
    def role(self) -> str:
        return self.user["role"] if self.user else ""


MESSAGES = {
    "saved": "Изменения сохранены.",
    "registered": "Регистрация завершена. Войдите с указанными логином и паролем.",
    "registered_company": "Аккаунт компании создан. Войти можно сразу, публикация кейсов — после проверки администратором.",
    "applied": "Заявка подана. Следите за уведомлениями и статусом в личном кабинете.",
    "favorite_on": "Кейс добавлен в избранное.",
    "favorite_off": "Кейс убран из избранного.",
    "case_created": "Кейс создан и отправлен на модерацию.",
    "case_updated": "Кейс обновлён и отправлен на модерацию.",
    "project_created": "Проект опубликован в вашем портфолио.",
    "result_saved": "Результат отправлен компании.",
    "team_created": "Команда сформирована.",
    "invited": "Приглашение отправлено студенту.",
    "invite_accepted": "Приглашение принято, заявка создана.",
    "invite_declined": "Приглашение отклонено.",
    "comment_added": "Комментарий добавлен.",
    "stage_saved": "Этап обновлён.",
    "logout": "Вы вышли из системы.",
    "password_changed": "Пароль изменён.",
}

ERRORS = {
    "login": "Неверный логин или пароль.",
    "blocked": "Учётная запись заблокирована администратором.",
    "fields": "Заполните обязательные поля.",
    "password": "Пароль не соответствует требованиям: минимум 8 символов, буквы и цифры.",
    "password_mismatch": "Пароли не совпадают.",
    "username_taken": "Пользователь с таким логином уже существует.",
    "email": "Укажите корректный адрес электронной почты.",
    "consent": "Необходимо согласие на обработку персональных данных.",
    "registration_closed": "Регистрация новых пользователей закрыта администратором.",
    "forbidden": "Для этого действия недостаточно прав.",
    "not_found": "Запись не найдена.",
    "already_applied": "Вы уже подали заявку на этот кейс.",
    "not_participant": "Действие доступно только участникам проекта.",
    "company_pending": "Публикация кейсов станет доступна после проверки компании администратором.",
    "upload": "Не удалось загрузить файл.",
    "csrf": "Форма устарела. Обновите страницу и повторите действие.",
    "rate": "Слишком много попыток входа. Повторите позже.",
    "team_members": "Выберите хотя бы одного участника команды.",
    "already_in_team": "Студент уже состоит в команде по этому кейсу.",
}


def go(path: str, msg: str = "", err: str = "") -> Redirect:
    separator = "&" if "?" in path else "?"
    if msg:
        return Redirect(f"{path}{separator}msg={msg}")
    if err:
        return Redirect(f"{path}{separator}err={err}")
    return Redirect(path)


def flash(ctx) -> str:
    parts = []
    msg = ctx.params.get("msg") or ""
    err = ctx.params.get("err") or ""
    if msg and msg in MESSAGES:
        parts.append(f"<div class='flash ok'>{esc(MESSAGES[msg])}</div>")
    if err:
        text = ERRORS.get(err) or err
        parts.append(f"<div class='flash bad'>{esc(text[:300])}</div>")
    return "".join(parts)


def options(values, selected="") -> str:
    out = []
    for value in values:
        mark = " selected" if str(value) == str(selected) else ""
        out.append(f'''<option value="{esc(value)}"{mark}>{esc(value)}</option>''')
    return "".join(out)


def course_options(selected="") -> str:
    out = []
    for number in range(1, 7):
        mark = " selected" if str(number) == str(selected) else ""
        out.append(f"<option value='{number}'{mark}>{number} курс</option>")
    return "".join(out)


def f_open(ctx, action: str, css: str = "", multipart: bool = False) -> str:
    enctype = " enctype='multipart/form-data'" if multipart else ""
    token = f"<input type='hidden' name='_csrf' value='{esc(ctx.csrf)}'>" if ctx.csrf else ""
    css_attr = f" class='{css}'" if css else ""
    return f"<form method='post' action='{esc(action)}'{css_attr}{enctype}>{token}"


def badge(status: str) -> str:
    mapping = {
        "Опубликован": "ok", "Выполнен": "ok", "Завершён": "ok", "Принята": "ok",
        "Одобрена": "ok", "Произведена": "ok", "Подтверждена": "ok",
        "На модерации": "wait", "Черновик": "wait", "Собеседование": "wait",
        "Отбор": "wait", "Выполняется": "wait", "На проверке": "wait",
        "Представлен результат": "wait", "Требуется доработка": "wait",
        "Отклонена": "bad", "Отклонён": "bad", "Скрыт": "bad", "Отклонено": "bad",
        "Ожидается": "wait", "Отправлено": "wait",
    }
    return f"<span class='state {mapping.get(status, '')}'>{esc(status)}</span>"


def unread_count(ctx) -> int:
    if not ctx.user:
        return 0
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (ctx.user["id"],)
        ).fetchone()[0]
    finally:
        conn.close()


def nav(ctx) -> str:
    links = [("/", "Витрина кейсов"), ("/projects", "Проекты студентов"), ("/rating", "Рейтинг")]
    user = ctx.user
    if user:
        if user["role"] == "student":
            links += [("/dashboard", "Мой кабинет"), ("/my-projects", "Мои проекты")]
        elif user["role"] == "company":
            links += [("/dashboard", "Кабинет компании"), ("/students", "Студенты"), ("/case/new", "Новый кейс")]
        else:
            links += [("/dashboard", "Администрирование"), ("/analytics", "Аналитика"), ("/audit", "Журнал")]
        count = unread_count(ctx)
        suffix = f" ({count})" if count else ""
        links += [("/notifications", f"Уведомления{suffix}")]
        links += [("/logout", "Выйти")]
    else:
        links += [("/login", "Войти"), ("/register", "Регистрация")]
    items = "".join(f"<a href='{href}'>{esc(label)}</a>" for href, label in links)
    return f"<nav class='nav'>{items}</nav>"


def layout(ctx, title: str, body: str) -> str:
    user = ctx.user
    role_badge = ""
    if user:
        role_name = ROLES.get(user["role"], user["role"])
        role_badge = (
            f"<div class='userbox'><b>{esc(user['full_name'])}</b>"
            f"<span>{esc(role_name)}</span></div>"
        )
    else:
        role_badge = ""
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)} — Витрина ИТ-проектов</title>"
        "<link rel='stylesheet' href='/static/style.css'>"
        "<link rel='stylesheet' href='/static/app.css'></head><body>"
        "<header><div class='brand'><div class='logo'>ИТ</div><div>"
        "<strong>Витрина ИТ-проектов</strong>"
        "<small>Уфимский университет науки и технологий</small>"
        f"</div></div>{role_badge}</header>{nav(ctx)}<main>{flash(ctx)}{body}</main>"
        "<footer>АИС «Витрина ИТ-проектов» · УУНиТ · 2026</footer></body></html>"
    )


def allow_roles(ctx, *roles) -> None:
    if not ctx.user:
        raise Redirect("/login")
    if ctx.user["role"] not in roles:
        raise HttpError(403, ERRORS["forbidden"])


def parse_list(text: str) -> list[str]:
    return [part.strip() for part in str(text or "").replace(";", ",").split(",") if part.strip()]


def link_out(url, label="") -> str:
    safe = safe_url(url)
    if not safe:
        return "—"
    return f"<a href='{esc(safe)}' target='_blank' rel='noopener'>{esc(label or safe)}</a>"


def num1(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f}".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def case_card(row) -> str:
    reward = row["reward_type"]
    if row["prize_fund"]:
        reward += " · " + money(row["prize_fund"])
    elif row["reward_amount"]:
        reward += " · " + money(row["reward_amount"])
    extra = ""
    if row["internship"]:
        extra = "<span class='flag'>стажировка</span>"
    if row["nda_required"]:
        extra += "<span class='flag'>NDA</span>"
    company = row["company_short"] if "company_short" in row.keys() and row["company_short"] else row["company_name"]
    return (
        "<article class='card'>"
        f"<div class='tags'><span>{esc(row['direction'])}</span><span>{esc(row['difficulty'])}</span>{extra}</div>"
        f"<h3><a href='/case/{row['id']}'>{esc(row['title'])}</a></h3>"
        f"<div class='company'>{esc(company)}</div>"
        f"<p>{esc(row['short_description'])}</p>"
        f"<div class='tech'>{esc(row['technologies'])}</div>"
        "<div class='card-bottom'>"
        f"<b>{esc(reward)}</b><span>до {esc(date_ru(row['deadline']))}</span>"
        "</div></article>"
    )


# --------------------------------------------------------------------------
# Авторизация и регистрация
# --------------------------------------------------------------------------
def login_page(ctx):
    if ctx.user:
        raise Redirect("/dashboard")
    demo = ""
    if DEMO_MODE:
        demo = (
            "<div class='demo'><b>Демонстрационные аккаунты</b>"
            "<p>Администратор: <code>admin</code> / <code>Admin12345!</code></p>"
            "<p>Компания: <code>company</code> / <code>Company123!</code></p>"
            "<p>Студент: <code>student01</code> / <code>Student123!</code></p></div>"
        )
    register_link = (
        "<p class='muted'>Нет аккаунта? <a href='/register'>Зарегистрироваться</a></p>"
        if REGISTRATION_OPEN else "<p class='muted'>Самостоятельная регистрация отключена.</p>"
    )
    body = (
        "<div class='auth panel'><h1>Вход</h1>"
        f"{f_open(ctx, '/login')}"
        "<label>Логин<input name='username' required autocomplete='username'></label>"
        "<label>Пароль<input type='password' name='password' required autocomplete='current-password'></label>"
        "<button>Войти</button></form>"
        f"{register_link}{demo}</div>"
    )
    return layout(ctx, "Вход", body)


def login_submit(ctx):
    username = (ctx.form.get("username") or "").strip()
    password = ctx.form.get("password") or ""
    if not username or not password:
        raise go("/login", err="login")
    key = f"{ctx.ip}|{username.lower()}"
    if core.login_retry_after(key):
        raise go("/login", err="rate")
    conn = db.connect()
    try:
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and user["blocked"]:
            raise go("/login", err="blocked")
        if user and db.verify_password(password, user["password"]):
            sid, _ = db.create_session(user["id"])
            conn.execute("UPDATE users SET last_login=? WHERE id=?", (now(), user["id"]))
            db.audit(conn, user["id"], "login", "user", user["id"], "Вход в систему")
            conn.commit()
            core.note_login_success(key)
            raise RedirectWithCookie("/dashboard", core.session_cookie(sid))
        core.note_login_failure(key)
        db.audit(conn, None, "login_failed", "user", None, f"Логин: {username[:60]}")
        conn.commit()
    finally:
        conn.close()
    raise go("/login", err="login")


def register_page(ctx):
    if ctx.user:
        raise Redirect("/dashboard")
    if not REGISTRATION_OPEN:
        return layout(ctx, "Регистрация", "<div class='panel'><h1>Регистрация закрыта</h1>"
                      "<p>Самостоятельная регистрация отключена администратором.</p></div>")
    body = (
        "<div class='panel'><h1>Регистрация</h1>"
        "<p class='muted'>Студенты получают доступ к витрине кейсов сразу. "
        "Компании могут публиковать кейсы после проверки администратором.</p>"
        f"{f_open(ctx, '/register')}"
        "<div class='twofields'>"
        "<label>Тип аккаунта<select name='role'>"
        "<option value='student'>Студент</option><option value='company'>Компания</option>"
        "</select></label>"
        "<label>Логин<input name='username' required minlength='3' maxlength='32' pattern='[A-Za-z0-9_.-]+'></label>"
        "</div>"
        "<div class='twofields'>"
        "<label>Пароль<input type='password' name='password' required minlength='8'></label>"
        "<label>Повторите пароль<input type='password' name='password2' required minlength='8'></label>"
        "</div>"
        "<label>ФИО / контактное лицо<input name='full_name' required maxlength='120'></label>"
        "<div class='twofields'>"
        "<label>Электронная почта<input type='email' name='email' required></label>"
        "<label>Телефон<input name='phone' maxlength='32'></label>"
        "</div>"
        "<fieldset class='group'><legend>Данные студента</legend>"
        "<div class='twofields'>"
        "<label>Институт / факультет<input name='institute' maxlength='120'></label>"
        "<label>Направление подготовки<input name='program' maxlength='160'></label>"
        "</div><div class='twofields'>"
        "<label>Курс<input name='course' maxlength='4'></label>"
        "<label>Учебная группа<input name='group_name' maxlength='40'></label>"
        "</div>"
        "<label>Компетенции (через запятую)<input name='skills' maxlength='300'></label>"
        "<label>Ссылка на GitHub / GitLab<input name='github' maxlength='300'></label>"
        "</fieldset>"
        "<fieldset class='group'><legend>Данные компании</legend>"
        "<div class='twofields'>"
        "<label>Название компании<input name='company_name' maxlength='160'></label>"
        "<label>Краткое название<input name='company_short' maxlength='60'></label>"
        "</div><div class='twofields'>"
        "<label>Отрасль<input name='industry' maxlength='80' placeholder='ИТ / разработка ПО'></label>"
        "<label>Сайт<input name='website' maxlength='200' placeholder='https://'></label>"
        "</div>"
        "<label>Описание компании<textarea name='company_description' maxlength='2000'></textarea></label>"
        "</fieldset>"
        "<label class='check'><input type='checkbox' name='consent' value='1' required>"
        " Согласен на обработку персональных данных</label>"
        "<button>Зарегистрироваться</button></form>"
        "<p class='muted'>Уже есть аккаунт? <a href='/login'>Войти</a></p></div>"
    )
    return layout(ctx, "Регистрация", body)


def register_submit(ctx):
    f = ctx.form
    role = "company" if f.get("role") == "company" else "student"
    username = (f.get("username") or "").strip()
    full_name = (f.get("full_name") or "").strip()
    email = (f.get("email") or "").strip()
    password = f.get("password") or ""
    if not REGISTRATION_OPEN:
        raise go("/register", err="registration_closed")
    if not username or not full_name or not email or not password:
        raise go("/register", err="fields")
    if not valid_email(email):
        raise go("/register", err="email")
    if password != (f.get("password2") or ""):
        raise go("/register", err="password_mismatch")
    if password_problem(password):
        raise go("/register", err="password")
    if not f.get("consent"):
        raise go("/register", err="consent")

    conn = db.connect()
    try:
        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise go("/register", err="username_taken")
        cursor = conn.execute(
            """INSERT INTO users(username,password,role,full_name,email,phone,institute,program,course,
               group_name,skills,bio,github,links,consent_at,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                username, db.hash_password(password), role, full_name, email, (f.get("phone") or "").strip(),
                (f.get("institute") or "").strip(), (f.get("program") or "").strip(),
                (f.get("course") or "").strip(), (f.get("group_name") or "").strip(),
                (f.get("skills") or "").strip(), "", (f.get("github") or "").strip(),
                "", now(), now(),
            ),
        )
        user_id = cursor.lastrowid
        msg = "registered"
        if role == "company":
            company_name = (f.get("company_name") or "").strip() or full_name
            conn.execute(
                """INSERT INTO companies(owner_user_id,name,short_name,description,industry,website,
                   contacts,approved,created_at) VALUES (?,?,?,?,?,?,?,0,?)""",
                (
                    user_id, company_name, (f.get("company_short") or "").strip(),
                    (f.get("company_description") or "").strip(),
                    (f.get("industry") or "").strip() or "ИТ",
                    safe_url(f.get("website")), email, now(),
                ),
            )
            db.notify_admins(conn, f"Новая компания «{company_name}» ожидает проверки", "/dashboard")
            msg = "registered_company"
        db.audit(conn, user_id, "register", "user", user_id, f"Роль: {role}")
        conn.commit()
    finally:
        conn.close()
    raise go("/login", msg=msg)


class RedirectWithCookie(Redirect):
    def __init__(self, url: str, cookie: str):
        super().__init__(url)
        self.cookie = cookie


def logout(ctx):
    db.delete_session(ctx.sid)
    raise RedirectWithCookie("/", core.clear_cookie())


# --------------------------------------------------------------------------
# Публичные страницы
# --------------------------------------------------------------------------
def home(ctx):
    p = ctx.params
    q = (p.get("q") or "").strip()
    direction = p.get("direction") or ""
    company = p.get("company") or ""
    difficulty = p.get("difficulty") or ""
    participation = p.get("participation") or ""
    work_format = p.get("work_format") or ""
    reward = p.get("reward") or ""
    paid = p.get("paid") or ""
    internship = p.get("internship") or ""
    course = p.get("course") or ""
    sort = p.get("sort") or "new"

    where = ["c.status IN ('Опубликован','Завершён')", "co.approved=1"]
    args: list = []
    if q:
        where.append("(c.title LIKE ? OR c.short_description LIKE ? OR c.technologies LIKE ? OR co.name LIKE ?)")
        args += [f"%{q}%"] * 4
    if direction:
        where.append("c.direction=?"); args.append(direction)
    if company:
        where.append("c.company_id=?"); args.append(int(company) if company.isdigit() else 0)
    if difficulty:
        where.append("c.difficulty=?"); args.append(difficulty)
    if participation:
        where.append("c.participation_format=?"); args.append(participation)
    if work_format:
        where.append("c.work_format=?"); args.append(work_format)
    if reward:
        where.append("c.reward_type=?"); args.append(reward)
    if paid:
        where.append("(c.prize_fund>0 OR c.reward_amount>0)")
    if internship:
        where.append("c.internship=1")
    if course:
        where.append("(c.course=? OR c.course=0)"); args.append(int(course) if course.isdigit() else 0)

    order = {
        "deadline": "c.deadline IS NULL, c.deadline",
        "reward": "(c.prize_fund + c.reward_amount) DESC",
        "new": "c.created_at DESC",
    }.get(sort, "c.created_at DESC")

    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT c.*, co.name company_name, co.short_name company_short FROM cases c "
            "JOIN companies co ON co.id=c.company_id WHERE " + " AND ".join(where) +
            f" ORDER BY {order} LIMIT 300", args,
        ).fetchall()
        directions = [r["direction"] for r in conn.execute(
            "SELECT DISTINCT direction FROM cases WHERE status IN ('Опубликован','Завершён') ORDER BY direction").fetchall()]
        companies = conn.execute(
            "SELECT id,name FROM companies WHERE approved=1 ORDER BY name").fetchall()
    finally:
        conn.close()

    dir_values = [d for d in DIRECTIONS if d in directions] + [d for d in directions if d not in DIRECTIONS]
    cards = "".join(case_card(r) for r in rows) or "<div class='empty'>Подходящих кейсов не найдено. Измените условия поиска.</div>"
    company_opts = "<option value=''>Все компании</option>" + "".join(
        f"<option value='{c['id']}'{' selected' if str(c['id']) == company else ''}>{esc(c['name'])}</option>"
        for c in companies
    )
    body = (
        "<section class='hero'><div><h1>Реальные ИТ-кейсы от компаний</h1>"
        "<p>Выбирайте проекты, собирайте команды, получайте опыт, отзывы, призы и предложения "
        "о стажировке. Университет и компании-партнёры подтверждают результаты в портфолио.</p></div>"
        f"<div class='hero-stat'><b>{len(rows)}</b><span>доступных кейсов</span></div></section>"
        "<details class='filters-panel' open><summary>Поиск и фильтры</summary>"
        "<form class='filters wide' method='get' action='/'>"
        f"<input name='q' value='{esc(q)}' placeholder='Поиск по названию, технологиям или компании'>"
        f"<select name='direction'><option value=''>Все направления</option>{options(dir_values, direction)}</select>"
        f"<select name='company'>{company_opts}</select>"
        f"<select name='difficulty'><option value=''>Любая сложность</option>{options(DIFFICULTIES, difficulty)}</select>"
        f"<select name='participation'><option value=''>Любой формат участия</option>{options(PARTICIPATION, participation)}</select>"
        f"<select name='work_format'><option value=''>Любой режим работы</option>{options(WORK_FORMATS, work_format)}</select>"
        f"<select name='reward'><option value=''>Любой тип вознаграждения</option>{options(REWARD_TYPES, reward)}</select>"
        f"<select name='course'><option value=''>Любой курс</option>{course_options(course)}</select>"
        f"<select name='sort'><option value='new'{' selected' if sort == 'new' else ''}>Сначала новые</option>"
        f"<option value='deadline'{' selected' if sort == 'deadline' else ''}>По сроку</option>"
        f"<option value='reward'{' selected' if sort == 'reward' else ''}>По вознаграждению</option></select>"
        "<label class='check'><input type='checkbox' name='paid' value='1'"
        f"{' checked' if paid else ''}> только с вознаграждением</label>"
        "<label class='check'><input type='checkbox' name='internship' value='1'"
        f"{' checked' if internship else ''}> со стажировкой</label>"
        "<div class='filter-actions'><button>Найти</button><a class='button secondary' href='/'>Сбросить</a></div>"
        "</form></details>"
        f"<section class='grid'>{cards}</section>"
    )
    return layout(ctx, "Витрина кейсов", body)


def case_detail(ctx):
    cid = int(ctx.params["cid"])
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT c.*, co.name company_name, co.short_name company_short, co.description company_description,"
            " co.website, co.industry, co.id company_id FROM cases c JOIN companies co ON co.id=c.company_id"
            " WHERE c.id=?", (cid,),
        ).fetchone()
        if not row:
            raise HttpError(404, "Кейс не найден.")
        user = ctx.user
        owner = False
        if user and user["role"] == "company":
            owned = conn.execute("SELECT id FROM companies WHERE owner_user_id=?", (user["id"],)).fetchone()
            owner = bool(owned and owned["id"] == row["company_id"])
        is_admin = bool(user and user["role"] == "admin")
        application = None
        favorite = False
        team = conn.execute("SELECT * FROM teams WHERE case_id=?", (cid,)).fetchone()
        members = conn.execute(
            "SELECT tm.role, u.full_name, u.id FROM team_members tm JOIN users u ON u.id=tm.user_id"
            " WHERE tm.team_id=?", (team["id"],),
        ).fetchall() if team else []
        winners = conn.execute(
            """SELECT u.full_name, u.id student_id, a.place, a.score FROM applications a
               JOIN users u ON u.id=a.student_id WHERE a.case_id=? AND a.place<>''
               ORDER BY a.place""", (cid,),
        ).fetchall()
        if user and user["role"] == "student":
            application = conn.execute(
                "SELECT * FROM applications WHERE case_id=? AND student_id=?", (cid, user["id"])).fetchone()
            favorite = bool(conn.execute(
                "SELECT 1 FROM favorites WHERE case_id=? AND student_id=?", (cid, user["id"])).fetchone())
        company_approved = True
        if not owner and not is_admin:
            company_approved = bool(conn.execute(
                "SELECT approved FROM companies WHERE id=?", (row["company_id"],)).fetchone()[0])
    finally:
        conn.close()

    if row["status"] not in ("Опубликован", "Завершён") and not owner and not is_admin:
        if not application:
            raise HttpError(404, "Кейс не найден или ещё не опубликован.")
    if not company_approved and not owner and not is_admin:
        raise HttpError(404, "Кейс не найден или компания ещё не подтверждена.")

    participant = bool(application and application["status"] in ("Принята", "Собеседование"))
    can_see_full = (not row["nda_required"]) or owner or is_admin or participant
    reward_short = row["reward_type"]
    if row["prize_fund"]:
        reward_short += " · " + money(row["prize_fund"])
    elif row["reward_amount"]:
        reward_short += " · " + money(row["reward_amount"])

    actions = ""
    if user and user["role"] == "student":
        toggle = "Убрать из избранного" if favorite else "В избранное"
        actions += (
            f"<div class='actions'>{f_open(ctx, f'/case/{cid}/favorite', 'inline')}"
            f"<button class='secondary'>{toggle}</button></form>"
        )
        if application:
            actions += f"<span class='success'>Заявка уже подана · статус: {esc(application['status'])}</span></div>"
        elif row["status"] != "Опубликован":
            actions += "<span class='muted'>Приём заявок по этому кейсу закрыт.</span></div>"
        else:
            actions += (
                "<div class='applybox'>"
                f"{f_open(ctx, f'/case/{cid}/apply')}"
                "<label>Сопроводительное письмо<textarea name='message' required "
                "placeholder='Коротко расскажите, почему хотите выполнить проект и что уже умеете'>"
                "</textarea></label>"
                "<div class='twofields'>"
                "<label>Ссылка на портфолио<input name='portfolio_url' placeholder='https://'></label>"
                "<label>Ссылка на GitHub<input name='github_url' placeholder='https://'></label>"
                "</div>"
                "<label>Ссылка на резюме<input name='resume_url' placeholder='https://'></label>"
                "<button>Подать заявку</button></form></div>"
            )
    elif user and user["role"] == "company" and owner:
        actions = (
            f"<div class='actions'><a class='button' href='/case/{cid}/edit'>Редактировать кейс</a>"
            f"<a class='button secondary' href='/case/{cid}/workspace'>Рабочая страница</a>"
            f"<a class='button secondary' href='/case/{cid}/applications'>Заявки и команда</a></div>"
        )
    elif user and user["role"] == "admin":
        actions = (
            f"<div class='actions'><a class='button secondary' href='/case/{cid}/workspace'>Рабочая страница</a>"
            f"{f_open(ctx, f'/admin/case/{cid}', 'inline')}"
            "<button name='status' value='Опубликован'>Опубликовать</button>"
            "<button name='status' value='Скрыт' class='danger'>Скрыть</button></form></div>"
        )
    elif not user:
        actions = "<div class='actions'><a class='button' href='/login'>Войти и подать заявку</a></div>"

    nda_note = ""
    if row["nda_required"] and not can_see_full:
        nda_note = ("<div class='notice warn'>Проект требует соглашения о конфиденциальности (NDA). "
                    "Полное техническое задание станет доступно после принятия заявки.</div>")
    moderation = ""
    if row["status"] not in ("Опубликован", "Завершён"):
        moderation = f"<div class='notice warn'>Статус кейса: {esc(row['status'])}. {esc(row['moderation_note'] or '')}</div>"

    if can_see_full:
        description_html = f"<p>{esc(row['description'])}</p>"
    else:
        description_html = (
            "<p class='muted'>Полное описание скрыто до подтверждения участия (NDA).</p>"
            f"<p>{esc(clip(row['description'], 400))}</p>"
        )
    team_block = ""
    if team:
        member_items = "".join(f"<li>{esc(m['full_name'])} — {esc(m['role'])}</li>" for m in members)
        team_block = (
            f"<h2>Команда проекта</h2><div class='panel'><b>{esc(team['name'])}</b>"
            f"<p class='muted'>Руководитель: {esc(team['mentor'] or 'не назначен')}</p>"
            f"<ul>{member_items}</ul></div>"
        )
    winners_block = ""
    if winners and row["status"] in ("Опубликован", "Завершён"):
        items = "".join(
            f"<tr><td>{esc(w['place'])}</td>"
            f"<td><a href='/student/{w['student_id']}'>{esc(w['full_name'])}</a></td>"
            f"<td>{esc(w['score'] if w['score'] is not None else '—')}</td></tr>" for w in winners)
        winners_block = (
            "<h2>Результаты и победители</h2><div class='tablewrap'><table>"
            "<tr><th>Место / номинация</th><th>Студент</th><th>Оценка</th></tr>"
            f"{items}</table></div>"
        )
    reward_section = ""
    if row["reward_details"]:
        reward_section = f"<h2>Условия вознаграждения</h2><p>{esc(row['reward_details'])}</p>"
    body = (
        f"<a class='back' href='/'>&larr; К витрине</a>{moderation}"
        "<div class='detail panel'>"
        f"<div class='tags'><span>{esc(row['direction'])}</span><span>{esc(row['difficulty'])}</span>"
        f"<span>{esc(row['participation_format'])}</span><span>{esc(row['work_format'])}</span>"
        f"{'<span>стажировка</span>' if row['internship'] else ''}</div>"
        f"<h1>{esc(row['title'])}</h1>"
        f"<div class='company big'><a href='/company/{row['company_id']}'>{esc(row['company_name'])}</a></div>"
        f"<p class='lead'>{esc(row['short_description'])}</p>"
        "<div class='facts'>"
        f"<div><b>Срок</b><span>{esc(date_ru(row['deadline']))}</span></div>"
        f"<div><b>Команда</b><span>до {int(row['team_size'] or 1)} чел.</span></div>"
        f"<div><b>Вознаграждение</b><span>{esc(reward_short)}</span></div>"
        f"<div><b>Статус</b><span>{badge(row['status'])}</span></div>"
        "</div>"
        "<h2>Описание задачи</h2>" + description_html + nda_note +
        f"<h2>Технологии</h2><p>{esc(row['technologies'] or 'не указаны')}</p>"
        f"<h2>Требования к участникам</h2><p>{esc(row['requirements'] or 'не указаны')}</p>"
        f"<h2>Критерии оценки</h2><p>{esc(row['evaluation'] or 'не указаны')}</p>"
        f"<h2>Права на результат</h2><p>{esc(row['rights_mode'])}</p>"
        f"{reward_section}{winners_block}"
        f"<h2>Компания</h2><p>{esc(row['company_description'])}</p>"
        f"{actions}{team_block}</div>"
    )
    return layout(ctx, row["title"], body)


def case_apply(ctx):
    allow_roles(ctx, "student")
    cid = int(ctx.params["cid"])
    message = (ctx.form.get("message") or "").strip()
    if not message:
        raise go(f"/case/{cid}", err="fields")
    conn = db.connect()
    try:
        case = conn.execute(
            "SELECT c.*, co.owner_user_id, co.approved FROM cases c JOIN companies co ON co.id=c.company_id"
            " WHERE c.id=?", (cid,),
        ).fetchone()
        if not case or case["status"] != "Опубликован" or not case["approved"]:
            raise HttpError(404, "Кейс недоступен для заявок.")
        if conn.execute("SELECT 1 FROM applications WHERE case_id=? AND student_id=?",
                        (cid, ctx.user["id"])).fetchone():
            raise go(f"/case/{cid}", err="already_applied")
        conn.execute(
            """INSERT INTO applications(case_id,student_id,message,portfolio_url,github_url,resume_url,
               status,project_status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, ctx.user["id"], message[:4000], safe_url(ctx.form.get("portfolio_url")),
             safe_url(ctx.form.get("github_url")), safe_url(ctx.form.get("resume_url")),
             "Подана", "Заявка", now(), now()),
        )
        db.notify(conn, case["owner_user_id"],
                  f"Новая заявка от {ctx.user['full_name']} на кейс «{case['title']}»", f"/case/{cid}/applications")
        db.audit(conn, ctx.user["id"], "application_create", "case", cid, ctx.user["full_name"])
        conn.commit()
    finally:
        conn.close()
    raise go(f"/case/{cid}", msg="applied")


def favorite_toggle(ctx):
    allow_roles(ctx, "student")
    cid = int(ctx.params["cid"])
    conn = db.connect()
    try:
        row = conn.execute("SELECT id FROM favorites WHERE student_id=? AND case_id=?",
                           (ctx.user["id"], cid)).fetchone()
        if row:
            conn.execute("DELETE FROM favorites WHERE id=?", (row["id"],))
            message = "favorite_off"
        else:
            conn.execute("INSERT INTO favorites(student_id,case_id) VALUES (?,?)", (ctx.user["id"], cid))
            message = "favorite_on"
        conn.commit()
    finally:
        conn.close()
    raise go(f"/case/{cid}", msg=message)


def company_page(ctx):
    company_id = int(ctx.params["company_id"])
    conn = db.connect()
    try:
        company = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        if not company:
            raise HttpError(404, "Компания не найдена.")
        is_admin = bool(ctx.user and ctx.user["role"] == "admin")
        owner = bool(ctx.user and ctx.user["role"] == "company" and company["owner_user_id"] == ctx.user["id"])
        if not company["approved"] and not is_admin and not owner:
            raise HttpError(404, "Карточка компании недоступна.")
        rows = conn.execute(
            "SELECT c.*, co.name company_name, co.short_name company_short FROM cases c "
            "JOIN companies co ON co.id=c.company_id WHERE c.company_id=? AND c.status IN ('Опубликован','Завершён')"
            " ORDER BY c.created_at DESC", (company_id,),
        ).fetchall()
        total_cases = conn.execute("SELECT COUNT(*) FROM cases WHERE company_id=?", (company_id,)).fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(DISTINCT a.case_id) FROM applications a JOIN cases c ON c.id=a.case_id"
            " WHERE c.company_id=? AND a.project_status IN ('Выполнен','Завершён')", (company_id,),
        ).fetchone()[0]
        students = conn.execute(
            "SELECT COUNT(DISTINCT a.student_id) FROM applications a JOIN cases c ON c.id=a.case_id"
            " WHERE c.company_id=?", (company_id,),
        ).fetchone()[0]
        techs = conn.execute(
            "SELECT technologies FROM cases WHERE company_id=? AND status IN ('Опубликован','Завершён')", (company_id,),
        ).fetchall()
    finally:
        conn.close()
    tech_set = sorted({t.strip() for row in techs for t in str(row["technologies"]).split(",") if t.strip()})
    cards = "".join(case_card(r) for r in rows) or "<div class='empty'>Опубликованных кейсов пока нет.</div>"
    admin_actions = ""
    if ctx.user and ctx.user["role"] == "admin":
        buttons = "<button name='approved' value='1'>Подтвердить компанию</button>"
        if company["approved"]:
            buttons += "<button name='approved' value='0' class='danger'>Снять подтверждение</button>"
        admin_actions = f"<div class='actions'>{f_open(ctx, f'/admin/company/{company_id}', 'inline')}{buttons}</form></div>"
    body = (
        "<section class='hero small'><div>"
        f"<h1>{esc(company['name'])}</h1>"
        f"<p>{esc(company['industry'])} · {esc(company['short_name'] or '')}</p></div>"
        f"<div class='hero-stat'><b>{total_cases}</b><span>кейсов на платформе</span></div></section>"
        "<div class='two'><div class='panel'>"
        f"<h2>О компании</h2><p>{esc(company['description'])}</p>"
        f"<p><b>Сайт:</b> {link_out(company['website'])}</p>"
        f"<p><b>Контакты:</b> {esc(company['contacts'] or '—')}</p>"
        f"{admin_actions}</div>"
        "<div class='panel'><h2>Показатели</h2>"
        f"<div class='stats small'><div><b>{completed}</b><span>завершено кейсов</span></div>"
        f"<div><b>{students}</b><span>студентов участвовало</span></div>"
        f"<div><b>{len(tech_set)}</b><span>технологий</span></div></div></div></div>"
        "<h2>Размещённые кейсы</h2>"
        f"<section class='grid'>{cards}</section>"
    )
    return layout(ctx, company["name"], body)


def projects(ctx):
    q = (ctx.params.get("q") or "").strip()
    direction = ctx.params.get("direction") or ""
    conn = db.connect()
    try:
        sql = ("SELECT p.*, u.full_name, u.institute, u.program FROM student_projects p "
               "JOIN users u ON u.id=p.student_id WHERE p.status='Опубликован'")
        args: list = []
        if q:
            sql += (" AND (p.title LIKE ? OR p.technologies LIKE ? OR p.direction LIKE ?"
                    " OR u.full_name LIKE ? OR p.description LIKE ?)")
            args += [f"%{q}%"] * 5
        if direction:
            sql += " AND p.direction=?"
            args.append(direction)
        sql += " ORDER BY p.created_at DESC LIMIT 300"
        rows = conn.execute(sql, args).fetchall()
        directions = [r["direction"] for r in conn.execute(
            "SELECT DISTINCT direction FROM student_projects WHERE status='Опубликован' ORDER BY direction").fetchall()]
    finally:
        conn.close()
    cards = "".join(
        "<article class='card'>"
        f"<div class='tags'><span>{esc(r['direction'])}</span></div>"
        f"<h3><a href='/project/{r['id']}'>{esc(r['title'])}</a></h3>"
        f"<div class='company'>{esc(r['full_name'])} · {esc(r['institute'] or '')}</div>"
        f"<p>{esc(r['short_description'])}</p>"
        f"<div class='tech'>{esc(r['technologies'])}</div>"
        f"<div class='card-bottom'><b>{esc(r['needs'] or 'Открытый проект')}</b></div></article>"
        for r in rows
    ) or "<div class='empty'>Проекты не найдены.</div>"
    body = (
        "<section class='hero'><div><h1>Проекты студентов</h1>"
        "<p>Готовые разработки, pet-проекты, хакатоны и исследовательские работы. "
        "Компании могут находить команды и приглашать студентов к сотрудничеству.</p></div>"
        f"<div class='hero-stat'><b>{len(rows)}</b><span>проектов</span></div></section>"
        "<form class='filters' method='get' action='/projects'>"
        f"<input name='q' value='{esc(q)}' placeholder='Поиск по проектам, технологиям или автору'>"
        f"<select name='direction'><option value=''>Все направления</option>{options(directions, direction)}</select>"
        "<button>Найти</button></form>"
        f"<section class='grid'>{cards}</section>"
    )
    return layout(ctx, "Проекты студентов", body)


def project_detail(ctx):
    pid = int(ctx.params["pid"])
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT p.*, u.full_name, u.institute, u.program, u.course, u.skills, u.id student_id,"
            " u.github FROM student_projects p JOIN users u ON u.id=p.student_id WHERE p.id=?", (pid,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HttpError(404, "Проект не найден.")
    links = "".join(
        f"<a class='button secondary' target='_blank' rel='noopener' href='{esc(url)}'>{esc(label)}</a>"
        for label, url in (("Репозиторий", row["repo_url"]), ("Демо", row["demo_url"]),
                           ("Презентация", row["presentation_url"])) if safe_url(url)
    )
    body = (
        f"<a class='back' href='/projects'>&larr; К проектам</a>"
        "<div class='detail panel'>"
        f"<div class='tags'><span>{esc(row['direction'])}</span></div>"
        f"<h1>{esc(row['title'])}</h1>"
        f"<div class='company big'><a href='/student/{row['student_id']}'>{esc(row['full_name'])}</a>"
        f" · {esc(row['institute'] or '')}</div>"
        f"<p class='lead'>{esc(row['short_description'])}</p>"
        f"<h2>Описание</h2><p>{esc(row['description'])}</p>"
        f"<h2>Технологии</h2><p>{esc(row['technologies'] or 'не указаны')}</p>"
        f"<h2>Автор открыт к предложениям</h2><p>{esc(row['needs'] or 'не указано')}</p>"
        f"<div class='actions'>{links}<a class='button secondary' href='/student/{row['student_id']}'>"
        "Портфолио автора</a></div></div>"
    )
    return layout(ctx, row["title"], body)


def portfolio(ctx):
    student_id = int(ctx.params["student_id"])
    conn = db.connect()
    try:
        student = conn.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
        if not student:
            raise HttpError(404, "Студент не найден.")
        projects = conn.execute(
            "SELECT * FROM student_projects WHERE student_id=? AND status='Опубликован' ORDER BY created_at DESC",
            (student_id,),
        ).fetchall()
        completed = conn.execute(
            """SELECT a.*, c.title, c.direction, co.name company_name, co.id company_id
               FROM applications a JOIN cases c ON c.id=a.case_id JOIN companies co ON co.id=c.company_id
               WHERE a.student_id=? AND a.project_status IN ('Выполнен','Завершён')
               ORDER BY a.created_at DESC""", (student_id,),
        ).fetchall()
    finally:
        conn.close()
    skills = parse_list(student["skills"])
    skill_tags = "".join(f"<span>{esc(s)}</span>" for s in skills) or "<span>не указаны</span>"
    project_cards = "".join(
        f"<article class='card'><div class='tags'><span>{esc(p['direction'])}</span></div>"
        f"<h3><a href='/project/{p['id']}'>{esc(p['title'])}</a></h3><p>{esc(p['short_description'])}</p>"
        f"<div class='tech'>{esc(p['technologies'])}</div></article>" for p in projects
    ) or "<div class='empty'>Собственных проектов пока нет.</div>"
    rows = ""
    for a in completed:
        rows += (
            f"<tr><td><a href='/case/{a['case_id']}'>{esc(a['title'])}</a><br>"
            f"<small>{esc(a['company_name'])}</small></td>"
            f"<td>{badge(a['project_status'])}</td>"
            f"<td>{esc(a['score'] if a['score'] is not None else '—')}</td>"
            f"<td>{esc(a['place'] or '—')}</td>"
            f"<td>{esc(clip(a['review'], 160) or '—')}</td></tr>"
        )
    if not rows:
        rows = "<tr><td colspan='5'>Подтверждённых компанией проектов пока нет.</td></tr>"
    wins = [a["place"] for a in completed if a["place"]]
    scores = [a["score"] for a in completed if a["score"] is not None]
    avg_text = num1(sum(scores) / len(scores)) if scores else "—"
    github_block = ""
    if safe_url(student["github"]):
        github_block = f"<p><b>GitHub:</b> {link_out(student['github'])}</p>"
    body = (
        f"<a class='back' href='/projects'>&larr; К проектам</a>"
        "<section class='hero small'><div>"
        f"<h1>{esc(student['full_name'])}</h1>"
        f"<p>{esc(student['institute'] or '')} · {esc(student['program'] or '')} · "
        f"{esc(student['course'] or '—')} курс · {esc(student['group_name'] or '')}</p></div>"
        f"<div class='hero-stat'><b>{len(completed)}</b><span>подтверждённых проектов</span></div></section>"
        "<div class='two'><div class='panel'><h2>О себе</h2>"
        f"<p>{esc(student['bio'] or 'не заполнено')}</p>"
        f"<h2>Компетенции</h2><div class='tags'>{skill_tags}</div>"
        f"{github_block}</div><div class='panel'><h2>Достижения</h2>"
        f"<p><b>Призовые места:</b> {esc(', '.join(wins)) if wins else 'пока нет'}</p>"
        f"<p><b>Средняя оценка:</b> {avg_text}</p>"
        "</div></div>"
        "<h2>Проекты, подтверждённые компаниями</h2>"
        "<div class='tablewrap'><table><tr><th>Кейс</th><th>Статус</th><th>Оценка</th>"
        f"<th>Место</th><th>Отзыв</th></tr>{rows}</table></div>"
        f"<h2>Собственные проекты</h2><section class='grid'>{project_cards}</section>"
    )
    return layout(ctx, student["full_name"], body)


def rating_page(ctx):
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT u.id, u.full_name, u.institute, u.program, u.course,
                      COUNT(a.id) completed,
                      AVG(a.score) avg_score,
                      SUM(CASE WHEN a.place <> '' THEN 1 ELSE 0 END) wins
               FROM users u JOIN applications a ON a.student_id=u.id
               WHERE u.role='student' AND u.blocked=0
                 AND a.project_status IN ('Выполнен','Завершён')
               GROUP BY u.id ORDER BY completed DESC, avg_score DESC LIMIT 50"""
        ).fetchall()
    finally:
        conn.close()
    items = ""
    for index, r in enumerate(rows, start=1):
        avg = num1(r["avg_score"])
        items += (
            f"<tr><td>{index}</td><td><a href='/student/{r['id']}'>{esc(r['full_name'])}</a></td>"
            f"<td>{esc(r['institute'] or '')}</td><td>{esc(r['course'] or '—')}</td>"
            f"<td>{r['completed']}</td><td>{avg}</td><td>{r['wins']}</td></tr>"
        )
    if not items:
        items = "<tr><td colspan='7'>Пока нет завершённых проектов — рейтинг появится после первых защит.</td></tr>"
    body = (
        "<section class='hero small'><div><h1>Рейтинг студентов</h1>"
        "<p>Рейтинг учитывает количество подтверждённых компаниями проектов, среднюю оценку и "
        "призовые места. Он не является единственным критерием оценки обучающегося.</p></div></section>"
        "<div class='panel'><div class='tablewrap'><table><tr><th>#</th><th>Студент</th><th>Институт</th>"
        f"<th>Курс</th><th>Завершено</th><th>Средняя оценка</th><th>Победы</th></tr>{items}</table></div></div>"
    )
    return layout(ctx, "Рейтинг студентов", body)


# --------------------------------------------------------------------------
# Кабинет студента
# --------------------------------------------------------------------------
def split_ids(text) -> list[int]:
    result = []
    for chunk in str(text or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            result.append(int(chunk))
    return result


def company_of(conn, user_id):
    return conn.execute("SELECT * FROM companies WHERE owner_user_id=?", (user_id,)).fetchone()


def owned_case(conn, user, case_id):
    return conn.execute(
        "SELECT c.*, co.owner_user_id FROM cases c JOIN companies co ON co.id=c.company_id"
        " WHERE c.id=? AND co.owner_user_id=?", (case_id, user["id"]),
    ).fetchone()


def student_dashboard(ctx):
    allow_roles(ctx, "student")
    user = ctx.user
    conn = db.connect()
    try:
        apps = conn.execute(
            """SELECT a.*, c.title, c.direction, c.reward_type, c.deadline, co.name company_name
               FROM applications a JOIN cases c ON c.id=a.case_id JOIN companies co ON co.id=c.company_id
               WHERE a.student_id=? ORDER BY a.created_at DESC""", (user["id"],),
        ).fetchall()
        favs = conn.execute(
            "SELECT c.*, co.name company_name, co.short_name company_short FROM favorites f"
            " JOIN cases c ON c.id=f.case_id JOIN companies co ON co.id=c.company_id"
            " WHERE f.student_id=? AND c.status IN ('Опубликован','Завершён')", (user["id"],),
        ).fetchall()
        invites = conn.execute(
            """SELECT i.*, co.name company_name, c.title FROM invitations i
               JOIN companies co ON co.id=i.company_id LEFT JOIN cases c ON c.id=i.case_id
               WHERE i.student_id=? AND i.status='Отправлено' ORDER BY i.created_at DESC""", (user["id"],),
        ).fetchall()
        teams = conn.execute(
            """SELECT t.*, c.title FROM team_members tm JOIN teams t ON t.id=tm.team_id
               JOIN cases c ON c.id=t.case_id WHERE tm.user_id=?""", (user["id"],),
        ).fetchall()
        unread = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (user["id"],)).fetchone()[0]
    finally:
        conn.close()

    rows = ""
    for a in apps:
        rows += (
            f"<tr><td><a href='/case/{a['case_id']}'>{esc(a['title'])}</a><br>"
            f"<small>{esc(a['company_name'])}</small></td>"
            f"<td>{badge(a['status'])}</td><td>{badge(a['project_status'])}</td>"
            f"<td>{esc(a['score'] if a['score'] is not None else '—')}</td>"
            f"<td>{esc(a['place'] or '—')}</td>"
            f"<td>{esc(a['payment_status'])}</td></tr>"
        )
    if not rows:
        rows = "<tr><td colspan='6'>Заявок пока нет. Выберите кейс на витрине.</td></tr>"

    invite_block = ""
    for inv in invites:
        invite_block += (
            "<div class='notice'>"
            f"<p><b>{esc(inv['company_name'])}</b> приглашает вас в проект "
            f"«{esc(inv['title'] or 'без привязки к кейсу')}».</p>"
            f"<p class='muted'>{esc(inv['message'])}</p>"
            f"{f_open(ctx, '/invitation/' + str(inv['id']) + '/respond', 'inline')}"
            "<button name='action' value='accept'>Принять</button>"
            "<button name='action' value='decline' class='secondary'>Отклонить</button>"
            "</form></div>"
        )

    team_block = "".join(
        f"<li><a href='/case/{t['case_id']}/workspace'>«{esc(t['title'])}»</a> — команда {esc(t['name'])}</li>"
        for t in teams
    ) or "<li>Вы пока не в команде.</li>"

    fav_cards = "".join(case_card(r) for r in favs) or "<div class='empty'>В избранном пока нет кейсов.</div>"
    body = (
        "<section class='hero small'><div><h1>Личный кабинет студента</h1>"
        f"<p>{esc(user['full_name'])} · {esc(user['group_name'] or 'группа не указана')} · "
        f"{esc(user['program'] or '')}</p></div>"
        f"<div class='hero-stat'><b>{len(apps)}</b><span>заявок</span></div></section>"
        + ("<div class='notice warn'>У вас есть непрочитанные уведомления. "
           f"<a href='/notifications'>Открыть ({unread})</a></div>" if unread else "")
        + f"{invite_block}"
        "<div class='two'><div class='panel'><h2>Профиль и компетенции</h2>"
        f"{f_open(ctx, '/profile')}"
        f"<label>ФИО<input name='full_name' value='{esc(user['full_name'])}' required></label>"
        "<div class='twofields'>"
        f"<label>Электронная почта<input name='email' type='email' value='{esc(user['email'])}'></label>"
        f"<label>Телефон<input name='phone' value='{esc(user['phone'])}'></label></div>"
        "<div class='twofields'>"
        f"<label>Институт<input name='institute' value='{esc(user['institute'])}'></label>"
        f"<label>Направление подготовки<input name='program' value='{esc(user['program'])}'></label></div>"
        "<div class='twofields'>"
        f"<label>Курс<input name='course' value='{esc(user['course'])}'></label>"
        f"<label>Группа<input name='group_name' value='{esc(user['group_name'])}'></label></div>"
        f"<label>Компетенции (через запятую)<input name='skills' value='{esc(user['skills'])}'></label>"
        f"<label>GitHub / GitLab<input name='github' value='{esc(user['github'])}'></label>"
        f"<label>О себе<textarea name='bio'>{esc(user['bio'])}</textarea></label>"
        "<button>Сохранить профиль</button></form>"
        "<h2>Смена пароля</h2>"
        f"{f_open(ctx, '/password')}"
        "<div class='twofields'>"
        "<label>Текущий пароль<input type='password' name='old_password' required></label>"
        "<label>Новый пароль<input type='password' name='new_password' required minlength='8'></label></div>"
        "<button class='secondary'>Изменить пароль</button></form></div>"
        "<div class='panel'><h2>Мои заявки</h2><div class='tablewrap'><table>"
        "<tr><th>Кейс</th><th>Решение</th><th>Этап</th><th>Оценка</th><th>Место</th><th>Выплата</th></tr>"
        f"{rows}</table></div>"
        f"<h2>Мои команды</h2><ul>{team_block}</ul>"
        "<p><a class='button secondary' href='/my-projects'>Мои собственные проекты</a> "
        "<a class='button secondary' href='/student/" + str(user["id"]) + "'>Публичное портфолио</a></p>"
        "</div></div>"
        f"<h2>Избранные кейсы</h2><section class='grid'>{fav_cards}</section>"
    )
    return layout(ctx, "Личный кабинет", body)


def profile_save(ctx):
    allow_roles(ctx, "student")
    f = ctx.form
    full_name = (f.get("full_name") or "").strip()
    if not full_name:
        raise go("/dashboard", err="fields")
    email = (f.get("email") or "").strip()
    if email and not valid_email(email):
        raise go("/dashboard", err="email")
    conn = db.connect()
    try:
        conn.execute(
            """UPDATE users SET full_name=?,email=?,phone=?,institute=?,program=?,course=?,
               group_name=?,skills=?,github=?,bio=? WHERE id=?""",
            (full_name, email, (f.get("phone") or "").strip(), (f.get("institute") or "").strip(),
             (f.get("program") or "").strip(), (f.get("course") or "").strip(),
             (f.get("group_name") or "").strip(), (f.get("skills") or "").strip(),
             safe_url(f.get("github")), (f.get("bio") or "").strip()[:2000], ctx.user["id"]),
        )
        db.audit(conn, ctx.user["id"], "profile_update", "user", ctx.user["id"], "")
        conn.commit()
    finally:
        conn.close()
    raise go("/dashboard", msg="saved")


def password_change(ctx):
    allow_roles(ctx, "admin", "company", "student")
    old = ctx.form.get("old_password") or ""
    new = ctx.form.get("new_password") or ""
    if not db.verify_password(old, ctx.user["password"]):
        raise go("/dashboard", err="login")
    problem = password_problem(new)
    if problem:
        raise go("/dashboard", err="password")
    conn = db.connect()
    try:
        conn.execute("UPDATE users SET password=? WHERE id=?", (db.hash_password(new), ctx.user["id"]))
        db.audit(conn, ctx.user["id"], "password_change", "user", ctx.user["id"], "")
        conn.commit()
    finally:
        conn.close()
    raise go("/dashboard", msg="password_changed")


def my_projects(ctx):
    allow_roles(ctx, "student")
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM student_projects WHERE student_id=? ORDER BY created_at DESC", (ctx.user["id"],),
        ).fetchall()
    finally:
        conn.close()
    cards = "".join(
        "<article class='card'>"
        f"<h3><a href='/project/{r['id']}'>{esc(r['title'])}</a></h3>"
        f"<p>{esc(r['short_description'])}</p><div class='tech'>{esc(r['technologies'])}</div>"
        f"<div class='card-bottom'>{badge(r['status'])}</div></article>"
        for r in rows
    ) or "<div class='empty'>Вы ещё не публиковали проекты.</div>"
    form = (
        "<div class='panel'><h2>Опубликовать проект</h2>"
        f"{f_open(ctx, '/project/new')}"
        "<label>Название<input name='title' required maxlength='160'></label>"
        "<label>Краткое описание<input name='short_description' required maxlength='300'></label>"
        "<label>Полное описание<textarea name='description' required></textarea></label>"
        "<div class='twofields'>"
        f"<label>Направление<select name='direction'>{options(DIRECTIONS)}</select></label>"
        "<label>Технологии<input name='technologies' maxlength='300'></label></div>"
        "<label>Репозиторий<input name='repo_url' placeholder='https://github.com/...'></label>"
        "<label>Демо<input name='demo_url' placeholder='https://'></label>"
        "<label>Презентация<input name='presentation_url' placeholder='https://'></label>"
        "<label>Что вы ищете<textarea name='needs' placeholder='Например: наставника, компанию, стажировку'></textarea></label>"
        "<button>Опубликовать</button></form></div>"
    )
    return layout(ctx, "Мои проекты",
                  f"<h1>Мои проекты</h1><section class='grid'>{cards}</section>{form}")


def project_new(ctx):
    allow_roles(ctx, "student")
    f = ctx.form
    title = (f.get("title") or "").strip()
    short = (f.get("short_description") or "").strip()
    description = (f.get("description") or "").strip()
    if not title or not short or not description:
        raise go("/my-projects", err="fields")
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO student_projects(student_id,title,short_description,description,direction,
               technologies,repo_url,demo_url,presentation_url,needs,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ctx.user["id"], title[:160], short[:300], description[:8000],
             (f.get("direction") or "Другое").strip(), (f.get("technologies") or "").strip()[:300],
             safe_url(f.get("repo_url")), safe_url(f.get("demo_url")), safe_url(f.get("presentation_url")),
             (f.get("needs") or "").strip()[:500], "Опубликован", now()),
        )
        db.audit(conn, ctx.user["id"], "project_create", "student_project", None, title[:120])
        conn.commit()
    finally:
        conn.close()
    raise go("/my-projects", msg="project_created")


def result_submit(ctx):
    allow_roles(ctx, "student")
    aid = int(ctx.params["aid"])
    conn = db.connect()
    try:
        row = conn.execute(
            """SELECT a.*, c.title, co.owner_user_id FROM applications a JOIN cases c ON c.id=a.case_id
               JOIN companies co ON co.id=c.company_id WHERE a.id=? AND a.student_id=?""",
            (aid, ctx.user["id"]),
        ).fetchone()
        if not row:
            raise HttpError(404, "Заявка не найдена.")
        if row["status"] not in ("Принята",):
            raise HttpError(403, "Результат можно отправить после принятия заявки.")
        uploaded = [f for f in ctx.files if f["field"] == "result_file"]
        file_id = row["result_file_id"]
        if uploaded and uploaded[0].get("filename"):
            meta = core.save_upload(uploaded[0])
            cursor = conn.execute(
                """INSERT INTO files(user_id,case_id,application_id,original_name,stored_name,size,
                   content_type,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (ctx.user["id"], row["case_id"], aid, meta["original_name"], meta["stored_name"],
                 meta["size"], meta["content_type"], now()),
            )
            file_id = cursor.lastrowid
        note = (ctx.form.get("result_note") or row["result_note"] or "").strip()[:4000]
        url = safe_url(ctx.form.get("result_url")) or row["result_url"]
        if not note and not url and not file_id:
            raise go("/dashboard", err="fields")
        conn.execute(
            "UPDATE applications SET result_note=?, result_url=?, result_file_id=?,"
            " project_status='Представлен результат', updated_at=? WHERE id=?",
            (note, url, file_id, now(), aid),
        )
        db.notify(conn, row["owner_user_id"],
                  f"Студент отправил результат по кейсу «{row['title']}»", f"/case/{row['case_id']}/applications")
        db.audit(conn, ctx.user["id"], "result_submit", "application", aid, row["title"][:120])
        conn.commit()
    finally:
        conn.close()
    raise go("/dashboard", msg="result_saved")


def invitation_respond(ctx):
    allow_roles(ctx, "student")
    invitation_id = int(ctx.params["iid"])
    action = ctx.form.get("action") or ""
    conn = db.connect()
    try:
        invite = conn.execute(
            "SELECT * FROM invitations WHERE id=? AND student_id=?", (invitation_id, ctx.user["id"]),
        ).fetchone()
        if not invite:
            raise HttpError(404, "Приглашение не найдено.")
        if action == "accept":
            conn.execute("UPDATE invitations SET status='Принято' WHERE id=?", (invitation_id,))
            if invite["case_id"]:
                existing = conn.execute(
                    "SELECT 1 FROM applications WHERE case_id=? AND student_id=?",
                    (invite["case_id"], ctx.user["id"]),
                ).fetchone()
                if not existing:
                    conn.execute(
                        """INSERT INTO applications(case_id,student_id,message,status,project_status,
                           invited,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
                        (invite["case_id"], ctx.user["id"], "Отклик на приглашение компании",
                         "Принята", "Принята", 1, now(), now()),
                    )
            db.audit(conn, ctx.user["id"], "invitation_accept", "invitation", invitation_id, "")
            conn.commit()
            raise go("/dashboard", msg="invite_accepted")
        conn.execute("UPDATE invitations SET status='Отклонено' WHERE id=?", (invitation_id,))
        db.audit(conn, ctx.user["id"], "invitation_decline", "invitation", invitation_id, "")
        conn.commit()
    finally:
        conn.close()
    raise go("/dashboard", msg="invite_declined")


# --------------------------------------------------------------------------
# Кабинет компании
# --------------------------------------------------------------------------
def company_dashboard(ctx):
    allow_roles(ctx, "company")
    user = ctx.user
    conn = db.connect()
    try:
        co = company_of(conn, user["id"])
        cases = conn.execute(
            "SELECT * FROM cases WHERE company_id=? ORDER BY created_at DESC", (co["id"],),
        ).fetchall() if co else []
        stats = {}
        if co:
            stats["cases"] = len(cases)
            stats["published"] = sum(1 for c in cases if c["status"] == "Опубликован")
            stats["apps"] = conn.execute(
                "SELECT COUNT(*) FROM applications a JOIN cases c ON c.id=a.case_id WHERE c.company_id=?",
                (co["id"],)).fetchone()[0]
            stats["active"] = conn.execute(
                """SELECT COUNT(*) FROM applications a JOIN cases c ON c.id=a.case_id
                   WHERE c.company_id=? AND a.project_status IN ('Принята','Выполняется','На проверке',
                   'Требуется доработка','Представлен результат')""", (co["id"],)).fetchone()[0]
            stats["done"] = conn.execute(
                """SELECT COUNT(*) FROM applications a JOIN cases c ON c.id=a.case_id
                   WHERE c.company_id=? AND a.project_status IN ('Выполнен','Завершён')""",
                (co["id"],)).fetchone()[0]
        recent = conn.execute(
            """SELECT a.*, c.title, u.full_name FROM applications a JOIN cases c ON c.id=a.case_id
               JOIN users u ON u.id=a.student_id WHERE c.company_id=? ORDER BY a.created_at DESC LIMIT 15""",
            (co["id"],)).fetchall() if co else []
    finally:
        conn.close()

    if not co:
        return layout(ctx, "Кабинет компании",
                      "<div class='panel'><h1>Компания не зарегистрирована</h1>"
                      "<p>Обратитесь к администратору платформы.</p></div>")

    pending = "" if co["approved"] else (
        "<div class='notice warn'>Компания ожидает проверки администратором. "
        f"Публикация кейсов станет доступна после подтверждения. {esc(co['moderation_note'] or '')}</div>"
    )
    case_rows = "".join(
        f"<tr><td><a href='/case/{c['id']}'>{esc(c['title'])}</a></td><td>{badge(c['status'])}</td>"
        f"<td>{esc(c['reward_type'])}</td><td>{esc(date_ru(c['deadline']))}</td>"
        f"<td><a href='/case/{c['id']}/applications'>Заявки</a> · <a href='/case/{c['id']}/workspace'>Проект</a>"
        f" · <a href='/case/{c['id']}/edit'>Изменить</a></td></tr>"
        for c in cases
    ) or "<tr><td colspan='5'>Кейсов пока нет.</td></tr>"
    recent_rows = "".join(
        f"<tr><td><a href='/case/{r['case_id']}/applications'>{esc(r['title'])}</a></td>"
        f"<td>{esc(r['full_name'])}</td><td>{badge(r['status'])}</td>"
        f"<td>{badge(r['project_status'])}</td></tr>" for r in recent
    ) or "<tr><td colspan='4'>Заявок пока нет.</td></tr>"
    body = (
        f"<section class='hero small'><div><h1>Кабинет компании</h1>"
        f"<p>{esc(co['name'])} · {esc(co['industry'])}</p></div>"
        "<a class='button' href='/case/new'>+ Разместить кейс</a></section>"
        f"{pending}"
        f"<section class='stats'><div><b>{stats['cases']}</b><span>кейсов</span></div>"
        f"<div><b>{stats['published']}</b><span>опубликовано</span></div>"
        f"<div><b>{stats['apps']}</b><span>заявок</span></div>"
        f"<div><b>{stats['active']}</b><span>в работе</span></div>"
        f"<div><b>{stats['done']}</b><span>завершено</span></div></section>"
        "<div class='panel'><h2>Карточка компании</h2>"
        f"{f_open(ctx, '/company/profile')}"
        "<div class='twofields'>"
        f"<label>Название<input name='name' value='{esc(co['name'])}' required></label>"
        f"<label>Краткое название<input name='short_name' value='{esc(co['short_name'])}'></label></div>"
        "<div class='twofields'>"
        f"<label>Отрасль<input name='industry' value='{esc(co['industry'])}'></label>"
        f"<label>Сайт<input name='website' value='{esc(co['website'])}' placeholder='https://'></label></div>"
        f"<label>Контакты<input name='contacts' value='{esc(co['contacts'])}'></label>"
        f"<label>Описание<textarea name='description'>{esc(co['description'])}</textarea></label>"
        "<button>Сохранить карточку</button></form>"
        f"<p><a href='/company/{co['id']}'>Публичная карточка компании</a></p></div>"
        "<div class='panel'><h2>Мои кейсы</h2><div class='tablewrap'><table>"
        "<tr><th>Кейс</th><th>Статус</th><th>Тип</th><th>Срок</th><th>Действия</th></tr>"
        f"{case_rows}</table></div></div>"
        "<div class='panel'><h2>Последние заявки</h2><div class='tablewrap'><table>"
        f"<tr><th>Кейс</th><th>Студент</th><th>Решение</th><th>Этап</th></tr>{recent_rows}</table></div></div>"
    )
    return layout(ctx, "Кабинет компании", body)


def company_profile_save(ctx):
    allow_roles(ctx, "company")
    f = ctx.form
    name = (f.get("name") or "").strip()
    if not name:
        raise go("/dashboard", err="fields")
    conn = db.connect()
    try:
        co = company_of(conn, ctx.user["id"])
        if not co:
            raise HttpError(404, "Компания не найдена.")
        conn.execute(
            """UPDATE companies SET name=?,short_name=?,description=?,industry=?,website=?,contacts=?
               WHERE id=?""",
            (name[:160], (f.get("short_name") or "").strip()[:60],
             (f.get("description") or "").strip()[:4000], (f.get("industry") or "").strip()[:80],
             safe_url(f.get("website")), (f.get("contacts") or "").strip()[:300], co["id"]),
        )
        db.audit(conn, ctx.user["id"], "company_update", "company", co["id"], name[:120])
        conn.commit()
    finally:
        conn.close()
    raise go("/dashboard", msg="saved")


def _case_form(ctx, row=None):
    values = {
        "title": "", "short_description": "", "description": "", "technologies": "",
        "difficulty": "Средний", "participation_format": "Командный", "work_format": "Дистанционный",
        "team_size": "4", "deadline": "", "reward_type": "Образовательный", "reward_amount": "0",
        "prize_fund": "0", "reward_details": "", "requirements": "", "evaluation": "",
        "rights_mode": "Результаты остаются у авторов", "course": "0",
    }
    checked_internship = ""
    checked_nda = ""
    direction = DIRECTIONS[0]
    if row is not None:
        for key in values:
            if key in row.keys():
                values[key] = row[key] if row[key] is not None else ""
        direction = row["direction"] or DIRECTIONS[0]
        checked_internship = " checked" if row["internship"] else ""
        checked_nda = " checked" if row["nda_required"] else ""
    rights = ["Результаты остаются у авторов", "Простая неисключительная лицензия компании",
              "Передача исключительного права по отдельному соглашению", "Open-source"]
    action = f"/case/{row['id']}/edit" if row is not None else "/case/new"
    return (
        f"<a class='back' href='/dashboard'>&larr; В кабинет</a>"
        f"<div class='panel'><h1>{'Редактирование кейса' if row is not None else 'Новый ИТ-кейс'}</h1>"
        "<p class='muted'>После сохранения кейс отправляется на модерацию администратору.</p>"
        f"{f_open(ctx, action)}"
        f"<label>Название<input name='title' required maxlength='160' value='{esc(values['title'])}'></label>"
        f"<label>Краткое описание<input name='short_description' required maxlength='300' "
        f"value='{esc(values['short_description'])}'></label>"
        f"<label>Полное техническое задание<textarea name='description' required>{esc(values['description'])}</textarea></label>"
        "<div class='twofields'>"
        f"<label>Направление<select name='direction'>{options(DIRECTIONS, direction)}</select></label>"
        f"<label>Технологии<input name='technologies' value='{esc(values['technologies'])}' "
        "placeholder='Python, FastAPI, Docker'></label></div>"
        "<div class='twofields'>"
        f"<label>Сложность<select name='difficulty'>{options(DIFFICULTIES, values['difficulty'])}</select></label>"
        f"<label>Формат участия<select name='participation_format'>{options(PARTICIPATION, values['participation_format'])}</select></label></div>"
        "<div class='twofields'>"
        f"<label>Режим работы<select name='work_format'>{options(WORK_FORMATS, values['work_format'])}</select></label>"
        f"<label>Макс. участников<input name='team_size' type='number' min='1' max='20' value='{esc(values['team_size'])}'></label></div>"
        "<div class='twofields'>"
        f"<label>Срок<input name='deadline' type='date' value='{esc(values['deadline'])}'></label>"
        f"<label>Курс обучения (0 — любой)<input name='course' type='number' min='0' max='6' value='{esc(values['course'])}'></label></div>"
        "<div class='twofields'>"
        f"<label>Тип вознаграждения<select name='reward_type'>{options(REWARD_TYPES, values['reward_type'])}</select></label>"
        f"<label>Размер вознаграждения, ₽<input name='reward_amount' type='number' min='0' value='{esc(values['reward_amount'])}'></label></div>"
        f"<label>Призовой фонд, ₽<input name='prize_fund' type='number' min='0' value='{esc(values['prize_fund'])}'></label>"
        f"<label>Условия поощрения<textarea name='reward_details'>{esc(values['reward_details'])}</textarea></label>"
        f"<label>Требования к участникам<textarea name='requirements'>{esc(values['requirements'])}</textarea></label>"
        f"<label>Критерии оценки<textarea name='evaluation'>{esc(values['evaluation'])}</textarea></label>"
        f"<label>Права на результат<select name='rights_mode'>{options(rights, values['rights_mode'])}</select></label>"
        f"<label class='check'><input type='checkbox' name='nda_required' value='1'{checked_nda}>"
        " Требует соглашения о конфиденциальности (NDA)</label>"
        f"<label class='check'><input type='checkbox' name='internship' value='1'{checked_internship}>"
        " Возможна стажировка по итогам</label>"
        "<button>Отправить на модерацию</button></form></div>"
    )


def case_form(ctx):
    allow_roles(ctx, "company")
    conn = db.connect()
    try:
        co = company_of(conn, ctx.user["id"])
    finally:
        conn.close()
    if not co:
        raise HttpError(404, "Компания не найдена.")
    if not co["approved"]:
        return layout(ctx, "Новый кейс",
                      "<div class='panel'><h1>Компания на проверке</h1>"
                      "<p>Размещение кейсов станет доступно после подтверждения компании администратором.</p>"
                      f"<a class='button' href='/dashboard'>Вернуться в кабинет</a></div>")
    return layout(ctx, "Новый кейс", _case_form(ctx))


def case_edit(ctx):
    allow_roles(ctx, "company")
    cid = int(ctx.params["cid"])
    conn = db.connect()
    try:
        row = owned_case(conn, ctx.user, cid)
    finally:
        conn.close()
    if not row:
        raise HttpError(403, ERRORS["forbidden"])
    return layout(ctx, "Редактирование кейса", _case_form(ctx, row))


def _case_values(form):
    values = {
        "title": (form.get("title") or "").strip(),
        "short_description": (form.get("short_description") or "").strip(),
        "description": (form.get("description") or "").strip(),
        "direction": (form.get("direction") or "Другое").strip(),
        "technologies": (form.get("technologies") or "").strip(),
        "difficulty": form.get("difficulty") or "Средний",
        "participation_format": form.get("participation_format") or "Командный",
        "work_format": form.get("work_format") or "Дистанционный",
        "team_size": max(1, min(20, core.int_or(form.get("team_size"), 1))),
        "deadline": (form.get("deadline") or "").strip(),
        "reward_type": form.get("reward_type") or "Образовательный",
        "reward_amount": max(0, core.int_or(form.get("reward_amount"), 0)),
        "prize_fund": max(0, core.int_or(form.get("prize_fund"), 0)),
        "reward_details": (form.get("reward_details") or "").strip(),
        "requirements": (form.get("requirements") or "").strip(),
        "evaluation": (form.get("evaluation") or "").strip(),
        "rights_mode": form.get("rights_mode") or "Результаты остаются у авторов",
        "nda_required": 1 if form.get("nda_required") else 0,
        "internship": 1 if form.get("internship") else 0,
        "course": max(0, min(6, core.int_or(form.get("course"), 0))),
    }
    return values


def case_create(ctx):
    allow_roles(ctx, "company")
    values = _case_values(ctx.form)
    if not values["title"] or not values["short_description"] or not values["description"]:
        raise go("/case/new", err="fields")
    conn = db.connect()
    try:
        co = company_of(conn, ctx.user["id"])
        if not co:
            raise HttpError(404, "Компания не найдена.")
        if not co["approved"]:
            raise go("/dashboard", err="company_pending")
        cursor = conn.execute(
            """INSERT INTO cases(company_id,title,short_description,description,direction,technologies,
               difficulty,participation_format,work_format,team_size,deadline,reward_type,reward_amount,
               prize_fund,reward_details,requirements,evaluation,rights_mode,nda_required,internship,
               course,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'На модерации',?,?)""",
            (co["id"], values["title"][:160], values["short_description"][:300],
             values["description"][:20000], values["direction"], values["technologies"][:300],
             values["difficulty"], values["participation_format"], values["work_format"],
             values["team_size"], values["deadline"], values["reward_type"], values["reward_amount"],
             values["prize_fund"], values["reward_details"][:2000], values["requirements"][:4000],
             values["evaluation"][:4000], values["rights_mode"], values["nda_required"],
             values["internship"], values["course"], now(), now()),
        )
        case_id = cursor.lastrowid
        db.notify_admins(conn, f"Новый кейс «{values['title']}» ожидает модерации", f"/case/{case_id}")
        db.audit(conn, ctx.user["id"], "case_create", "case", case_id, values["title"][:120])
        conn.commit()
    finally:
        conn.close()
    raise go("/dashboard", msg="case_created")


def case_update(ctx):
    allow_roles(ctx, "company")
    cid = int(ctx.params["cid"])
    values = _case_values(ctx.form)
    if not values["title"] or not values["short_description"] or not values["description"]:
        raise go(f"/case/{cid}/edit", err="fields")
    conn = db.connect()
    try:
        if not owned_case(conn, ctx.user, cid):
            raise HttpError(403, ERRORS["forbidden"])
        conn.execute(
            """UPDATE cases SET title=?,short_description=?,description=?,direction=?,technologies=?,
               difficulty=?,participation_format=?,work_format=?,team_size=?,deadline=?,reward_type=?,
               reward_amount=?,prize_fund=?,reward_details=?,requirements=?,evaluation=?,rights_mode=?,
               nda_required=?,internship=?,course=?,status='На модерации',moderation_note='',updated_at=?
               WHERE id=?""",
            (values["title"][:160], values["short_description"][:300], values["description"][:20000],
             values["direction"], values["technologies"][:300], values["difficulty"],
             values["participation_format"], values["work_format"], values["team_size"],
             values["deadline"], values["reward_type"], values["reward_amount"], values["prize_fund"],
             values["reward_details"][:2000], values["requirements"][:4000], values["evaluation"][:4000],
             values["rights_mode"], values["nda_required"], values["internship"], values["course"],
             now(), cid),
        )
        db.notify_admins(conn, f"Кейс «{values['title']}» обновлён и ожидает модерации", f"/case/{cid}")
        db.audit(conn, ctx.user["id"], "case_update", "case", cid, values["title"][:120])
        conn.commit()
    finally:
        conn.close()
    raise go("/dashboard", msg="case_updated")


def applications_page(ctx):
    allow_roles(ctx, "company", "admin")
    cid = int(ctx.params["cid"])
    conn = db.connect()
    try:
        if ctx.user["role"] == "admin":
            case = conn.execute(
                "SELECT c.*, co.name company_name FROM cases c JOIN companies co ON co.id=c.company_id"
                " WHERE c.id=?", (cid,)).fetchone()
        else:
            case = owned_case(conn, ctx.user, cid)
        if not case:
            raise HttpError(403, ERRORS["forbidden"])
        rows = conn.execute(
            """SELECT a.*, u.full_name, u.group_name, u.skills, u.program, u.course, u.email, u.id student_id
               FROM applications a JOIN users u ON u.id=a.student_id
               WHERE a.case_id=? ORDER BY a.created_at DESC""", (cid,),
        ).fetchall()
        team = conn.execute("SELECT * FROM teams WHERE case_id=?", (cid,)).fetchone()
        members = conn.execute(
            """SELECT tm.role, u.full_name, u.id FROM team_members tm JOIN users u ON u.id=tm.user_id
               WHERE tm.team_id=?""", (team["id"],),
        ).fetchall() if team else []
        files_rows = conn.execute(
            "SELECT * FROM files WHERE case_id=? ORDER BY created_at DESC", (cid,)).fetchall()
        company_name = case["company_name"] if "company_name" in case.keys() else conn.execute(
            "SELECT name FROM companies WHERE id=?", (case["company_id"],)).fetchone()[0]
    finally:
        conn.close()

    forms = ""
    accepted_options = []
    for a in rows:
        if a["status"] == "Принята":
            accepted_options.append(a)
        result = ""
        if a["result_url"] or a["result_note"] or a["result_file_id"]:
            result = (
                "<div class='result'><b>Результат:</b> "
                f"{link_out(a['result_url'])}<br>{esc(clip(a['result_note'], 200))}"
                + (f"<br><a href='/file/{a['result_file_id']}'>Скачать вложение</a>" if a["result_file_id"] else "")
                + "</div>"
            )
        forms += (
            "<div class='app-row'><div class='app-head'>"
            f"<div><a href='/student/{a['student_id']}'><b>{esc(a['full_name'])}</b></a>"
            f"<div class='muted'>{esc(a['group_name'] or '')} · {esc(a['program'] or '')} · "
            f"{esc(a['course'] or '—')} курс</div>"
            f"<div class='tags small'>{''.join(f'<span>{esc(s)}</span>' for s in parse_list(a['skills']))}</div></div>"
            f"<div>{badge(a['status'])} {badge(a['project_status'])}</div></div>"
            f"<p>{esc(a['message'])}</p>"
            f"<p class='muted'>Портфолио: {link_out(a['portfolio_url'])} · GitHub: {link_out(a['github_url'])}"
            f" · Резюме: {link_out(a['resume_url'])}</p>{result}"
            f"{f_open(ctx, '/application/' + str(a['id']) + '/update')}"
            "<div class='twofields'>"
            f"<label>Решение<select name='status'>{options(APPLICATION_STATUSES, a['status'])}</select></label>"
            f"<label>Этап<select name='project_status'>{options(PROJECT_STATUSES, a['project_status'])}</select></label></div>"
            "<div class='twofields'>"
            f"<label>Оценка (0–100)<input name='score' type='number' min='0' max='100' "
            f"value='{esc(a['score'] if a['score'] is not None else '')}'></label>"
            f"<label>Место / номинация<input name='place' value='{esc(a['place'])}'></label></div>"
            f"<label>Отзыв<textarea name='review'>{esc(a['review'])}</textarea></label>"
            f"<label>Статус выплаты<select name='payment_status'>{options(PAYMENT_STATUSES, a['payment_status'])}</select></label>"
            "<button>Сохранить</button></form></div>"
        )
    if not forms:
        forms = "<div class='empty'>Заявок пока нет.</div>"

    team_block = ""
    if team:
        team_block = (
            f"<div class='notice'><b>Команда «{esc(team['name'])}»</b>"
            f"<p class='muted'>Руководитель: {esc(team['mentor'] or 'не назначен')}</p><ul>"
            + "".join(f"<li>{esc(m['full_name'])} — {esc(m['role'])}</li>" for m in members)
            + "</ul></div>"
        )
    if accepted_options:
        rows_html = []
        for a in accepted_options:
            rows_html.append(
                f"<div class='member-row'><label class='check'>"
                f"<input type='checkbox' name='member' value='{a['student_id']}'> {esc(a['full_name'])}</label>"
                f"<select name='role_{a['student_id']}'>{options(TEAM_ROLES)}</select></div>"
            )
        member_inputs = "".join(rows_html)
        team_form = (
            "<div class='panel'><h2>Формирование команды</h2>"
            f"{f_open(ctx, f'/case/{cid}/team')}"
            "<div class='twofields'>"
            "<label>Название команды<input name='name' required maxlength='80'></label>"
            "<label>Руководитель / наставник<input name='mentor' maxlength='120'></label></div>"
            f"<div class='members'>{member_inputs}</div>"
            "<button>Сформировать команду</button></form></div>"
        )
    else:
        team_form = "<div class='notice'>Чтобы сформировать команду, примите хотя бы одну заявку.</div>"

    files_block = "".join(
        f"<li><a href='/file/{f['id']}'>{esc(f['original_name'])}</a> "
        f"<span class='muted'>{human_size(f['size'])}</span></li>" for f in files_rows
    )
    body = (
        f"<a class='back' href='/dashboard'>&larr; В кабинет</a>"
        "<section class='hero small'><div>"
        f"<h1>Заявки: {esc(case['title'])}</h1>"
        f"<p>{esc(company_name)} · {esc(case['direction'])} · {badge(case['status'])}</p></div></section>"
        f"{team_block}{team_form}"
        f"<h2>Кандидаты ({len(rows)})</h2>{forms}"
        f"<div class='panel'><h2>Файлы проекта</h2><ul>{files_block or '<li>Файлов пока нет.</li>'}</ul></div>"
    )
    return layout(ctx, "Заявки на кейс", body)


def application_update(ctx):
    allow_roles(ctx, "company", "admin")
    aid = int(ctx.params["aid"])
    f = ctx.form
    score_raw = (f.get("score") or "").strip()
    score = core.opt_int(score_raw)
    if score_raw and (score is None or score < 0 or score > 100):
        raise HttpError(400, "Оценка должна быть числом от 0 до 100.")
    status = f.get("status") if f.get("status") in APPLICATION_STATUSES else "Подана"
    project_status = f.get("project_status") if f.get("project_status") in PROJECT_STATUSES else "Заявка"
    payment = f.get("payment_status") if f.get("payment_status") in PAYMENT_STATUSES else "Не предусмотрена"
    conn = db.connect()
    try:
        own = conn.execute(
            """SELECT a.*, c.title, c.company_id, co.owner_user_id FROM applications a
               JOIN cases c ON c.id=a.case_id JOIN companies co ON co.id=c.company_id
               WHERE a.id=?""", (aid,),
        ).fetchone()
        if not own:
            raise HttpError(404, "Заявка не найдена.")
        if ctx.user["role"] != "admin" and own["owner_user_id"] != ctx.user["id"]:
            raise HttpError(403, ERRORS["forbidden"])
        if status == "Принята" and own["status"] != "Принята" and project_status == "Заявка":
            project_status = "Принята"
        conn.execute(
            """UPDATE applications SET status=?,project_status=?,score=?,place=?,review=?,
               payment_status=?,updated_at=? WHERE id=?""",
            (status, project_status, score, (f.get("place") or "").strip()[:80],
             (f.get("review") or "").strip()[:4000], payment, now(), aid),
        )
        db.notify(conn, own["student_id"],
                  f"Обновление по кейсу «{own['title']}»: {status} · {project_status}", "/dashboard")
        if f.get("place"):
            db.notify(conn, own["student_id"],
                      f"Вам присуждено место/номинация «{f.get('place')}» по кейсу «{own['title']}»", "/dashboard")
        db.audit(conn, ctx.user["id"], "application_update", "application", aid,
                 f"{status}/{project_status}/score={score}")
        conn.commit()
    finally:
        conn.close()
    raise go(f"/case/{own['case_id']}/applications", msg="saved")


def team_create(ctx):
    allow_roles(ctx, "company", "admin")
    cid = int(ctx.params["cid"])
    name = (ctx.form.get("name") or "").strip()
    if not name:
        raise go(f"/case/{cid}/applications", err="fields")
    member_ids = [uid for uid in split_ids(ctx.form.get("member"))]
    if not member_ids:
        raise go(f"/case/{cid}/applications", err="team_members")
    conn = db.connect()
    try:
        if ctx.user["role"] == "admin":
            case = conn.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
        else:
            case = owned_case(conn, ctx.user, cid)
        if not case:
            raise HttpError(403, ERRORS["forbidden"])
        existing = conn.execute("SELECT id FROM teams WHERE case_id=?", (cid,)).fetchone()
        if existing:
            team_id = existing["id"]
            conn.execute("DELETE FROM team_members WHERE team_id=?", (team_id,))
            conn.execute("UPDATE teams SET name=?,mentor=? WHERE id=?",
                         (name[:80], (ctx.form.get("mentor") or "").strip()[:120], team_id))
        else:
            cursor = conn.execute(
                "INSERT INTO teams(case_id,name,leader_user_id,mentor,created_at) VALUES (?,?,?,?,?)",
                (cid, name[:80], member_ids[0], (ctx.form.get("mentor") or "").strip()[:120], now()),
            )
            team_id = cursor.lastrowid
        for uid in member_ids:
            role = (ctx.form.get(f"role_{uid}") or "Иная роль").strip()[:60]
            conn.execute("INSERT OR IGNORE INTO team_members(team_id,user_id,role) VALUES (?,?,?)",
                         (team_id, uid, role))
            db.notify(conn, uid, f"Вас включили в команду «{name}» по кейсу «{case['title']}»",
                      f"/case/{cid}/workspace")
        db.audit(conn, ctx.user["id"], "team_create", "case", cid, name[:80])
        conn.commit()
    finally:
        conn.close()
    raise go(f"/case/{cid}/applications", msg="team_created")


def students_search(ctx):
    allow_roles(ctx, "company", "admin")
    q = (ctx.params.get("q") or "").strip()
    course = ctx.params.get("course") or ""
    institute = (ctx.params.get("institute") or "").strip()
    conn = db.connect()
    try:
        sql = ("SELECT u.*, COUNT(a.id) done, AVG(a.score) avg_score FROM users u "
               "LEFT JOIN applications a ON a.student_id=u.id AND a.project_status IN ('Выполнен','Завершён') "
               "WHERE u.role='student' AND u.blocked=0")
        args: list = []
        if q:
            sql += (" AND (u.full_name LIKE ? OR u.skills LIKE ? OR u.program LIKE ?"
                    " OR u.institute LIKE ? OR u.bio LIKE ?)")
            args += [f"%{q}%"] * 5
        if course:
            sql += " AND u.course=?"
            args.append(course)
        if institute:
            sql += " AND u.institute LIKE ?"
            args.append(f"%{institute}%")
        sql += " GROUP BY u.id ORDER BY done DESC, u.full_name LIMIT 100"
        rows = conn.execute(sql, args).fetchall()
        if ctx.user["role"] == "company":
            co = company_of(conn, ctx.user["id"])
            my_cases = conn.execute(
                "SELECT id,title FROM cases WHERE company_id=? ORDER BY created_at DESC",
                (co["id"],)).fetchall() if co else []
        else:
            my_cases = []
    finally:
        conn.close()
    case_opts = "".join(f"<option value='{c['id']}'>{esc(c['title'])}</option>" for c in my_cases)
    cards = ""
    for r in rows:
        avg = num1(r["avg_score"])
        invite = ""
        if my_cases:
            invite = (
                f"{f_open(ctx, '/invite', 'inline')}"
                f"<input type='hidden' name='student_id' value='{r['id']}'>"
                f"<select name='case_id'>{case_opts}</select>"
                "<input name='message' placeholder='Сообщение'>"
                "<button class='secondary'>Пригласить</button></form>"
            )
        cards += (
            "<article class='card'><h3>"
            f"<a href='/student/{r['id']}'>{esc(r['full_name'])}</a></h3>"
            f"<div class='company'>{esc(r['institute'] or '')} · {esc(r['program'] or '')} · "
            f"{esc(r['course'] or '—')} курс</div>"
            f"<div class='tags'>{''.join(f'<span>{esc(s)}</span>' for s in parse_list(r['skills']))}</div>"
            f"<p>{esc(clip(r['bio'], 200))}</p>"
            f"<div class='card-bottom'><b>Завершено: {r['done']}</b><span>Средняя оценка: {avg}</span></div>"
            f"<div class='actions'>{invite}</div></article>"
        )
    if not cards:
        cards = "<div class='empty'>Студенты не найдены.</div>"
    body = (
        "<section class='hero small'><div><h1>Поиск студентов</h1>"
        "<p>Ищите участников по компетенциям, курсу и институту, приглашайте в проекты.</p></div></section>"
        "<form class='filters' method='get' action='/students'>"
        f"<input name='q' value='{esc(q)}' placeholder='Компетенция, технология, ФИО'>"
        f"<input name='institute' value='{esc(institute)}' placeholder='Институт'>"
        f"<select name='course'><option value=''>Любой курс</option>{course_options(course)}</select>"
        "<button>Найти</button></form>"
        f"<section class='grid'>{cards}</section>"
    )
    return layout(ctx, "Поиск студентов", body)


def invite_student(ctx):
    allow_roles(ctx, "company")
    student_id = core.int_or(ctx.form.get("student_id"), 0)
    case_id = core.int_or(ctx.form.get("case_id"), 0)
    message = (ctx.form.get("message") or "").strip()[:1000]
    conn = db.connect()
    try:
        co = company_of(conn, ctx.user["id"])
        if not co:
            raise HttpError(404, "Компания не найдена.")
        case = conn.execute("SELECT title FROM cases WHERE id=? AND company_id=?", (case_id, co["id"])).fetchone()
        student = conn.execute("SELECT full_name FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
        if not case or not student:
            raise HttpError(404, "Студент или кейс не найдены.")
        conn.execute(
            "INSERT INTO invitations(company_id,student_id,case_id,message,status,created_at) VALUES (?,?,?,?,?,?)",
            (co["id"], student_id, case_id, message, "Отправлено", now()),
        )
        db.notify(conn, student_id,
                  f"Компания «{co['name']}» приглашает вас в проект «{case['title']}»", "/notifications")
        db.audit(conn, ctx.user["id"], "invite", "user", student_id, case["title"][:120])
        conn.commit()
    finally:
        conn.close()
    raise go("/students", msg="invited")


# --------------------------------------------------------------------------
# Рабочая страница проекта
# --------------------------------------------------------------------------
def workspace_access(conn, ctx, cid):
    case = conn.execute(
        "SELECT c.*, co.name company_name, co.owner_user_id FROM cases c JOIN companies co ON co.id=c.company_id"
        " WHERE c.id=?", (cid,),
    ).fetchone()
    if not case:
        raise HttpError(404, "Кейс не найден.")
    is_admin = ctx.user["role"] == "admin"
    is_owner = case["owner_user_id"] == ctx.user["id"]
    application = None
    is_member = False
    if ctx.user["role"] == "student":
        application = conn.execute(
            "SELECT * FROM applications WHERE case_id=? AND student_id=?", (cid, ctx.user["id"])).fetchone()
        is_member = bool(conn.execute(
            "SELECT 1 FROM team_members tm JOIN teams t ON t.id=tm.team_id"
            " WHERE t.case_id=? AND tm.user_id=?", (cid, ctx.user["id"])).fetchone())
    participant = bool(application and application["status"] in ("Принята", "Собеседование")) or is_member
    if not (is_admin or is_owner or participant):
        raise HttpError(403, ERRORS["not_participant"])
    return case, application, is_owner or is_admin


def workspace(ctx):
    allow_roles(ctx, "admin", "company", "student")
    cid = int(ctx.params["cid"])
    conn = db.connect()
    try:
        case, application, can_manage = workspace_access(conn, ctx, cid)
        stages = conn.execute("SELECT * FROM stages WHERE case_id=? ORDER BY id", (cid,)).fetchall()
        teams = conn.execute("SELECT * FROM teams WHERE case_id=?", (cid,)).fetchall()
        members = {}
        for team in teams:
            members[team["id"]] = conn.execute(
                """SELECT tm.role, u.full_name, u.id FROM team_members tm JOIN users u ON u.id=tm.user_id
                   WHERE tm.team_id=?""", (team["id"],)).fetchall()
        comments = conn.execute(
            """SELECT c.*, u.full_name, u.role FROM comments c JOIN users u ON u.id=c.user_id
               WHERE c.case_id=? ORDER BY c.id""", (cid,),
        ).fetchall()
        files_rows = conn.execute(
            "SELECT * FROM files WHERE case_id=? ORDER BY created_at DESC", (cid,)).fetchall()
        results = conn.execute(
            """SELECT a.*, u.full_name FROM applications a JOIN users u ON u.id=a.student_id
               WHERE a.case_id=? AND (a.result_note<>'' OR a.result_url<>'' OR a.result_file_id IS NOT NULL)""",
            (cid,),
        ).fetchall()
    finally:
        conn.close()

    done = sum(1 for s in stages if s["status"] == "Выполнена")
    percent = int(done * 100 / len(stages)) if stages else 0
    stage_rows = ""
    for s in stages:
        action = ""
        if can_manage:
            action = (
                f"{f_open(ctx, '/stage/' + str(s['id']) + '/update', 'inline')}"
                "<select name='status'>" + options(["Ожидается", "Выполняется", "Выполнена", "Просрочена"], s["status"]) +
                "</select><button class='small'>Сохранить</button></form>"
            )
        stage_rows += (
            f"<tr><td>{esc(s['title'])}</td><td>{esc(s['description'])}</td>"
            f"<td>{esc(date_ru(s['due_date']))}</td><td>{badge(s['status'])}</td><td>{action}</td></tr>"
        )
    if not stage_rows:
        stage_rows = "<tr><td colspan='5'>Этапы ещё не заданы.</td></tr>"

    add_stage = ""
    if can_manage:
        add_stage = (
            "<div class='panel'><h2>Добавить контрольную точку</h2>"
            f"{f_open(ctx, '/case/' + str(cid) + '/stage')}"
            "<div class='twofields'>"
            "<label>Название<input name='title' required maxlength='120'></label>"
            "<label>Срок<input name='due_date' type='date'></label></div>"
            "<label>Описание результата<textarea name='description'></textarea></label>"
            "<button>Добавить этап</button></form></div>"
        )

    team_block = ""
    for team in teams:
        items = "".join(f"<li>{esc(m['full_name'])} — {esc(m['role'])}</li>" for m in members[team["id"]])
        team_block += (
            f"<div class='notice'><b>Команда «{esc(team['name'])}»</b>"
            f"<p class='muted'>Руководитель: {esc(team['mentor'] or 'не назначен')}</p><ul>{items}</ul></div>"
        )

    result_form = ""
    if ctx.user["role"] == "student" and application and application["status"] == "Принята":
        uploaded = ""
        if application["result_file_id"]:
            uploaded = f"<p>Текущее вложение: <a href='/file/{application['result_file_id']}'>скачать</a></p>"
        result_form = (
            "<div class='panel'><h2>Представление результата</h2>" + uploaded +
            f"{f_open(ctx, '/application/' + str(application['id']) + '/result', multipart=True)}"
            "<label>Ссылка на решение / репозиторий<input name='result_url' placeholder='https://'></label>"
            f"<label>Описание результата<textarea name='result_note'>{esc(application['result_note'])}</textarea></label>"
            f"<label>Файл (до {MAX_UPLOAD_MB} МБ)<input type='file' name='result_file'></label>"
            "<button>Отправить результат</button></form></div>"
        )

    comment_items = "".join(
        f"<div class='comment'><b>{esc(c['full_name'])}</b> "
        f"<span class='muted'>{esc(c['created_at'])}</span><p>{esc(c['text'])}</p></div>"
        for c in comments
    ) or "<p class='muted'>Комментариев пока нет.</p>"

    files_block = "".join(
        f"<li><a href='/file/{f['id']}'>{esc(f['original_name'])}</a> "
        f"<span class='muted'>{human_size(f['size'])}</span></li>" for f in files_rows
    ) or "<li class='muted'>Файлов пока нет.</li>"

    results_block = "".join(
        f"<div class='result'><b>{esc(r['full_name'])}</b>"
        f"<p>{esc(r['result_note'])}</p><p>{link_out(r['result_url'])}</p>"
        + (f"<a href='/file/{r['result_file_id']}'>Скачать файл</a>" if r["result_file_id"] else "")
        + "</div>" for r in results
    ) or "<p class='muted'>Результатов пока нет.</p>"

    my_status = ""
    if application:
        my_status = (
            "<div class='panel'><h2>Моя заявка</h2>"
            f"<p>{badge(application['status'])} {badge(application['project_status'])}</p>"
            f"<p><b>Оценка:</b> {esc(application['score'] if application['score'] is not None else '—')} "
            f"· <b>Место:</b> {esc(application['place'] or '—')}</p>"
            f"<p><b>Отзыв:</b> {esc(application['review'] or 'пока нет')}</p></div>"
        )

    body = (
        f"<a class='back' href='/dashboard'>&larr; В кабинет</a>"
        "<section class='hero small'><div>"
        f"<h1>{esc(case['title'])}</h1>"
        f"<p>{esc(case['company_name'])} · {esc(case['direction'])} · {badge(case['status'])}</p></div>"
        f"<div class='hero-stat'><b>{percent}%</b><span>готовность этапов</span></div></section>"
        f"{my_status}{team_block}"
        "<div class='panel'><h2>Контрольные точки</h2><div class='tablewrap'><table>"
        "<tr><th>Этап</th><th>Результат</th><th>Срок</th><th>Статус</th><th></th></tr>"
        f"{stage_rows}</table></div></div>"
        f"{add_stage}{result_form}"
        "<div class='two'><div class='panel'><h2>История изменений</h2>"
        f"{comment_items}"
        f"{f_open(ctx, '/case/' + str(cid) + '/comment')}"
        "<textarea name='text' required placeholder='Комментарий к проекту'></textarea>"
        "<button>Отправить</button></form></div>"
        "<div class='panel'><h2>Результаты участников</h2>"
        f"{results_block}<h2>Файлы</h2><ul>{files_block}</ul></div></div>"
    )
    return layout(ctx, case["title"], body)


def stage_add(ctx):
    allow_roles(ctx, "admin", "company")
    cid = int(ctx.params["cid"])
    title = (ctx.form.get("title") or "").strip()
    if not title:
        raise go(f"/case/{cid}/workspace", err="fields")
    conn = db.connect()
    try:
        case, _, can_manage = workspace_access(conn, ctx, cid)
        if not can_manage:
            raise HttpError(403, ERRORS["forbidden"])
        conn.execute(
            "INSERT INTO stages(case_id,title,description,due_date,status,created_at) VALUES (?,?,?,?,?,?)",
            (cid, title[:120], (ctx.form.get("description") or "").strip()[:1000],
             (ctx.form.get("due_date") or "").strip(), "Ожидается", now()),
        )
        db.audit(conn, ctx.user["id"], "stage_add", "case", cid, title[:80])
        conn.commit()
    finally:
        conn.close()
    raise go(f"/case/{cid}/workspace", msg="stage_saved")


def stage_update(ctx):
    allow_roles(ctx, "admin", "company")
    sid = int(ctx.params["sid"])
    status = ctx.form.get("status") or "Ожидается"
    if status not in ("Ожидается", "Выполняется", "Выполнена", "Просрочена"):
        raise HttpError(400, "Неизвестный статус этапа.")
    conn = db.connect()
    try:
        stage = conn.execute("SELECT * FROM stages WHERE id=?", (sid,)).fetchone()
        if not stage:
            raise HttpError(404, "Этап не найден.")
        case, _, can_manage = workspace_access(conn, ctx, stage["case_id"])
        if not can_manage:
            raise HttpError(403, ERRORS["forbidden"])
        conn.execute("UPDATE stages SET status=? WHERE id=?", (status, sid))
        db.audit(conn, ctx.user["id"], "stage_update", "stage", sid, status)
        conn.commit()
    finally:
        conn.close()
    raise go(f"/case/{stage['case_id']}/workspace", msg="stage_saved")


def comment_add(ctx):
    allow_roles(ctx, "admin", "company", "student")
    cid = int(ctx.params["cid"])
    text = (ctx.form.get("text") or "").strip()
    if not text:
        raise go(f"/case/{cid}/workspace", err="fields")
    conn = db.connect()
    try:
        case, _, _ = workspace_access(conn, ctx, cid)
        conn.execute(
            "INSERT INTO comments(case_id,user_id,text,created_at) VALUES (?,?,?,?)",
            (cid, ctx.user["id"], text[:2000], now()),
        )
        if ctx.user["role"] == "student":
            db.notify(conn, case["owner_user_id"],
                      f"Новый комментарий от {ctx.user['full_name']} по кейсу «{case['title']}»",
                      f"/case/{cid}/workspace")
        else:
            for row in conn.execute(
                    "SELECT DISTINCT a.student_id FROM applications a WHERE a.case_id=?"
                    " AND a.status='Принята'", (cid,)).fetchall():
                db.notify(conn, row["student_id"],
                          f"Компания оставила комментарий по кейсу «{case['title']}»", f"/case/{cid}/workspace")
        db.audit(conn, ctx.user["id"], "comment_add", "case", cid, text[:80])
        conn.commit()
    finally:
        conn.close()
    raise go(f"/case/{cid}/workspace", msg="comment_added")


def notifications(ctx):
    allow_roles(ctx, "admin", "company", "student")
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
            (ctx.user["id"],),
        ).fetchall()
        conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (ctx.user["id"],))
        conn.commit()
    finally:
        conn.close()
    items = ""
    for r in rows:
        mark = "" if r["is_read"] else "<span class='flag'>новое</span>"
        text = esc(r["text"])
        if safe_url(r["link"]):
            text = f"<a href='{esc(r['link'])}'>{text}</a>"
        items += (
            f"<div class='notice'>{mark}<span class='muted'>{esc(r['created_at'])}</span>"
            f"<p>{text}</p></div>"
        )
    if not items:
        items = "<div class='empty'>Уведомлений пока нет.</div>"
    return layout(ctx, "Уведомления", f"<h1>Уведомления</h1><div class='panel'>{items}</div>")


# --------------------------------------------------------------------------
# Администрирование, аналитика, аудит
# --------------------------------------------------------------------------
def _period(ctx):
    date_from = (ctx.params.get("from") or "").strip()
    date_to = (ctx.params.get("to") or "").strip()
    return date_from, date_to


def _period_sql(field, date_from, date_to):
    clauses, args = [], []
    if date_from:
        clauses.append(f"{field} >= ?")
        args.append(date_from + " 00:00:00")
    if date_to:
        clauses.append(f"{field} <= ?")
        args.append(date_to + " 23:59:59")
    return clauses, args


def admin_dashboard(ctx):
    allow_roles(ctx, "admin")
    conn = db.connect()
    try:
        stats = {
            "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "students": conn.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0],
            "companies": conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
            "cases": conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
            "published": conn.execute("SELECT COUNT(*) FROM cases WHERE status='Опубликован'").fetchone()[0],
            "apps": conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0],
            "projects": conn.execute("SELECT COUNT(*) FROM student_projects").fetchone()[0],
            "completed": conn.execute(
                "SELECT COUNT(*) FROM applications WHERE project_status IN ('Выполнен','Завершён')").fetchone()[0],
            "prize": conn.execute("SELECT COALESCE(SUM(prize_fund+reward_amount),0) FROM cases").fetchone()[0],
        }
        pending_cases = conn.execute(
            "SELECT c.*, co.name company_name FROM cases c JOIN companies co ON co.id=c.company_id"
            " WHERE c.status='На модерации' ORDER BY c.created_at DESC").fetchall()
        pending_companies = conn.execute(
            "SELECT co.*, u.full_name, u.email FROM companies co JOIN users u ON u.id=co.owner_user_id"
            " WHERE co.approved=0 ORDER BY co.id DESC").fetchall()
        users = conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT 60").fetchall()
        recent_audit = conn.execute(
            """SELECT a.*, u.username FROM audit_log a LEFT JOIN users u ON u.id=a.user_id
               ORDER BY a.id DESC LIMIT 12""").fetchall()
        dirs = conn.execute(
            "SELECT direction, COUNT(*) n FROM cases GROUP BY direction ORDER BY n DESC").fetchall()
    finally:
        conn.close()

    case_rows = "".join(
        f"<tr><td><a href='/case/{r['id']}'>{esc(r['title'])}</a><br><small>{esc(r['company_name'])}</small></td>"
        f"<td>{esc(r['direction'])}</td><td>{esc(date_ru(r['created_at']))}</td>"
        f"<td>{f_open(ctx, '/admin/case/' + str(r['id']), 'inline')}"
        "<button name='status' value='Опубликован'>Опубликовать</button>"
        "<button name='status' value='Отклонён' class='danger'>Отклонить</button></form></td></tr>"
        for r in pending_cases
    ) or "<tr><td colspan='4'>Кейсов на модерации нет.</td></tr>"

    company_rows = "".join(
        f"<tr><td><a href='/company/{r['id']}'>{esc(r['name'])}</a><br><small>{esc(r['full_name'])}</small></td>"
        f"<td>{esc(r['industry'])}</td><td>{esc(r['email'])}</td>"
        f"<td>{f_open(ctx, '/admin/company/' + str(r['id']), 'inline')}"
        "<button name='approved' value='1'>Подтвердить</button>"
        "<button name='approved' value='0' class='danger'>Отклонить</button></form></td></tr>"
        for r in pending_companies
    ) or "<tr><td colspan='4'>Компаний на проверке нет.</td></tr>"

    user_rows = "".join(
        f"<tr><td>{esc(r['username'])}</td><td>{esc(r['full_name'])}</td><td>{esc(ROLES.get(r['role'], r['role']))}</td>"
        f"<td>{esc(r['email'])}</td><td>{esc(date_ru(r['created_at']))}</td>"
        f"<td>{'заблокирован' if r['blocked'] else 'активен'}</td>"
        f"<td>{f_open(ctx, '/admin/user/' + str(r['id']), 'inline')}"
        + ("<button name='blocked' value='1' class='danger'>Заблокировать</button>"
           if not r["blocked"] else "<button name='blocked' value='0'>Разблокировать</button>")
        + "</form></td></tr>"
        for r in users
    )

    audit_rows = "".join(
        f"<tr><td>{esc(r['created_at'])}</td><td>{esc(r['username'] or 'система')}</td>"
        f"<td>{esc(r['action'])}</td><td>{esc(r['details'])}</td></tr>"
        for r in recent_audit
    ) or "<tr><td colspan='4'>Журнал пуст.</td></tr>"

    chart = "".join(
        f"<div class='barrow'><span>{esc(r['direction'])}</span>"
        f"<div class='bar' style='width:{min(100, int(r['n']) * 14)}%'></div><b>{r['n']}</b></div>"
        for r in dirs
    ) or "<p class='muted'>Нет данных.</p>"

    body = (
        "<section class='hero small'><div><h1>Администрирование</h1>"
        "<p>Модерация контента, пользователи и сводная аналитика.</p></div>"
        "<a class='button' href='/analytics'>Аналитика и отчёты</a></section>"
        f"<section class='stats'><div><b>{stats['users']}</b><span>пользователей</span></div>"
        f"<div><b>{stats['students']}</b><span>студентов</span></div>"
        f"<div><b>{stats['companies']}</b><span>компаний</span></div>"
        f"<div><b>{stats['cases']}</b><span>кейсов</span></div>"
        f"<div><b>{stats['apps']}</b><span>заявок</span></div>"
        f"<div><b>{stats['completed']}</b><span>завершено</span></div></section>"
        "<div class='two'><div class='panel'><h2>Кейсы на модерации</h2><div class='tablewrap'><table>"
        "<tr><th>Кейс</th><th>Направление</th><th>Создан</th><th>Действие</th></tr>"
        f"{case_rows}</table></div></div>"
        "<div class='panel'><h2>Компании на проверке</h2><div class='tablewrap'><table>"
        f"<tr><th>Компания</th><th>Отрасль</th><th>Контакт</th><th>Действие</th></tr>{company_rows}</table></div>"
        f"<h2>Кейсы по направлениям</h2>{chart}</div></div>"
        "<div class='panel'><h2>Пользователи</h2><div class='tablewrap'><table>"
        "<tr><th>Логин</th><th>ФИО</th><th>Роль</th><th>E-mail</th><th>Регистрация</th><th>Статус</th><th></th></tr>"
        f"{user_rows}</table></div></div>"
        "<div class='panel'><h2>Последние действия</h2><div class='tablewrap'><table>"
        f"<tr><th>Время</th><th>Пользователь</th><th>Действие</th><th>Детали</th></tr>{audit_rows}</table></div>"
        "<p><a href='/audit'>Полный журнал действий</a></p></div>"
    )
    return layout(ctx, "Администрирование", body)


def admin_case_status(ctx):
    allow_roles(ctx, "admin")
    cid = int(ctx.params["cid"])
    status = ctx.form.get("status") or ""
    if status not in CASE_STATUSES:
        raise HttpError(400, "Неизвестный статус кейса.")
    note = (ctx.form.get("moderation_note") or "").strip()[:500]
    conn = db.connect()
    try:
        case = conn.execute(
            "SELECT c.*, co.owner_user_id FROM cases c JOIN companies co ON co.id=c.company_id WHERE c.id=?",
            (cid,)).fetchone()
        if not case:
            raise HttpError(404, "Кейс не найден.")
        conn.execute("UPDATE cases SET status=?, moderation_note=?, updated_at=? WHERE id=?",
                     (status, note, now(), cid))
        db.notify(conn, case["owner_user_id"],
                  f"Кейс «{case['title']}»: статус изменён на «{status}»", f"/case/{cid}")
        db.audit(conn, ctx.user["id"], "case_status", "case", cid, status)
        conn.commit()
    finally:
        conn.close()
    raise go("/dashboard", msg="saved")


def admin_company_status(ctx):
    allow_roles(ctx, "admin")
    company_id = int(ctx.params["company_id"])
    approved = 1 if ctx.form.get("approved") == "1" else 0
    note = (ctx.form.get("moderation_note") or "").strip()[:500]
    conn = db.connect()
    try:
        company = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        if not company:
            raise HttpError(404, "Компания не найдена.")
        conn.execute("UPDATE companies SET approved=?, moderation_note=? WHERE id=?",
                     (approved, note, company_id))
        db.notify(conn, company["owner_user_id"],
                  f"Компания «{company['name']}» {'подтверждена' if approved else 'не подтверждена'} администратором",
                  "/dashboard")
        db.audit(conn, ctx.user["id"], "company_status", "company", company_id,
                 "approved" if approved else "rejected")
        conn.commit()
    finally:
        conn.close()
    raise go("/dashboard", msg="saved")


def admin_user_block(ctx):
    allow_roles(ctx, "admin")
    user_id = int(ctx.params["user_id"])
    blocked = 1 if ctx.form.get("blocked") == "1" else 0
    if user_id == ctx.user["id"]:
        raise HttpError(400, "Нельзя заблокировать собственную учётную запись.")
    conn = db.connect()
    try:
        target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HttpError(404, "Пользователь не найден.")
        conn.execute("UPDATE users SET blocked=? WHERE id=?", (blocked, user_id))
        if blocked:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        db.audit(conn, ctx.user["id"], "user_block" if blocked else "user_unblock", "user", user_id,
                 target["username"])
        conn.commit()
    finally:
        conn.close()
    raise go("/dashboard", msg="saved")


def analytics_page(ctx):
    allow_roles(ctx, "admin")
    date_from, date_to = _period(ctx)
    conn = db.connect()
    try:
        app_clauses, app_args = _period_sql("a.created_at", date_from, date_to)
        app_where = (" AND " + " AND ".join(app_clauses)) if app_clauses else ""
        case_clauses, case_args = _period_sql("c.created_at", date_from, date_to)
        case_where = (" AND " + " AND ".join(case_clauses)) if case_clauses else ""
        kpi = {
            "students": conn.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0],
            "companies": conn.execute("SELECT COUNT(*) FROM companies WHERE approved=1").fetchone()[0],
            "participants": conn.execute(
                "SELECT COUNT(DISTINCT a.student_id) FROM applications a WHERE 1=1" + app_where, app_args).fetchone()[0],
            "apps": conn.execute("SELECT COUNT(*) FROM applications a WHERE 1=1" + app_where, app_args).fetchone()[0],
            "completed": conn.execute(
                "SELECT COUNT(*) FROM applications a WHERE a.project_status IN ('Выполнен','Завершён')"
                + app_where, app_args).fetchone()[0],
            "winners": conn.execute(
                "SELECT COUNT(*) FROM applications a WHERE a.place <> ''" + app_where, app_args).fetchone()[0],
            "paid": conn.execute(
                "SELECT COUNT(*) FROM applications a WHERE a.payment_status='Произведена'" + app_where, app_args).fetchone()[0],
            "avg": conn.execute(
                "SELECT AVG(score) FROM applications a WHERE score IS NOT NULL" + app_where, app_args).fetchone()[0],
            "published": conn.execute(
                "SELECT COUNT(*) FROM cases c WHERE c.status='Опубликован'" + case_where, case_args).fetchone()[0],
            "prize": conn.execute(
                "SELECT COALESCE(SUM(c.prize_fund),0) FROM cases c WHERE 1=1" + case_where, case_args).fetchone()[0],
            "reward": conn.execute(
                "SELECT COALESCE(SUM(c.reward_amount),0) FROM cases c WHERE 1=1" + case_where, case_args).fetchone()[0],
        }
        by_direction = conn.execute(
            """SELECT c.direction, COUNT(DISTINCT c.id) cases, COUNT(a.id) apps
               FROM cases c LEFT JOIN applications a ON a.case_id=c.id
               GROUP BY c.direction ORDER BY apps DESC, cases DESC""").fetchall()
        by_company = conn.execute(
            """SELECT co.name, COUNT(DISTINCT c.id) cases, COUNT(a.id) apps,
                      SUM(CASE WHEN a.project_status IN ('Выполнен','Завершён') THEN 1 ELSE 0 END) done
               FROM companies co LEFT JOIN cases c ON c.company_id=co.id
               LEFT JOIN applications a ON a.case_id=c.id
               GROUP BY co.id ORDER BY apps DESC LIMIT 20""").fetchall()
        by_reward = conn.execute(
            "SELECT reward_type, COUNT(*) n FROM cases GROUP BY reward_type ORDER BY n DESC").fetchall()
        by_status = conn.execute(
            "SELECT project_status, COUNT(*) n FROM applications GROUP BY project_status ORDER BY n DESC").fetchall()
    finally:
        conn.close()

    avg_text = num1(kpi["avg"])
    dir_rows = "".join(
        f"<tr><td>{esc(r['direction'])}</td><td>{r['cases']}</td><td>{r['apps']}</td></tr>" for r in by_direction)
    comp_rows = "".join(
        f"<tr><td>{esc(r['name'])}</td><td>{r['cases']}</td><td>{r['apps']}</td><td>{r['done']}</td></tr>"
        for r in by_company)
    reward_rows = "".join(
        f"<tr><td>{esc(r['reward_type'])}</td><td>{r['n']}</td></tr>" for r in by_reward)
    status_rows = "".join(
        f"<tr><td>{esc(r['project_status'])}</td><td>{r['n']}</td></tr>" for r in by_status)
    period_form = (
        "<form class='filters' method='get' action='/analytics'>"
        f"<label>С даты<input type='date' name='from' value='{esc(date_from)}'></label>"
        f"<label>По дату<input type='date' name='to' value='{esc(date_to)}'></label>"
        "<button>Применить</button></form>"
    )
    export_links = (
        f"<div class='actions'><a class='button' href='/export/analytics.csv?from={esc(date_from)}&to={esc(date_to)}'>"
        "Экспорт CSV</a>"
        f"<a class='button secondary' href='/export/analytics.xls?from={esc(date_from)}&to={esc(date_to)}'>"
        "Экспорт Excel</a>"
        f"<a class='button secondary' href='/export/cases.csv'>Кейсы (CSV)</a>"
        f"<a class='button secondary' href='/export/applications.csv'>Заявки (CSV)</a>"
        f"<a class='button secondary' href='/export/students.csv'>Студенты (CSV)</a>"
        f"<a class='button secondary' href='/export/companies.csv'>Компании (CSV)</a></div>"
    )
    body = (
        "<section class='hero small'><div><h1>Аналитика и отчёты</h1>"
        "<p>Сводные показатели по компаниям, проектам, студентам и вознаграждениям.</p></div></section>"
        f"{period_form}{export_links}"
        f"<section class='stats'><div><b>{kpi['students']}</b><span>студентов</span></div>"
        f"<div><b>{kpi['companies']}</b><span>активных компаний</span></div>"
        f"<div><b>{kpi['apps']}</b><span>заявок за период</span></div>"
        f"<div><b>{kpi['participants']}</b><span>участников</span></div>"
        f"<div><b>{kpi['completed']}</b><span>завершено</span></div>"
        f"<div><b>{kpi['winners']}</b><span>победителей</span></div>"
        f"<div><b>{kpi['paid']}</b><span>выплат произведено</span></div>"
        f"<div><b>{avg_text}</b><span>средняя оценка</span></div>"
        f"<div><b>{money(kpi['prize'])}</b><span>призовой фонд</span></div>"
        f"<div><b>{money(kpi['reward'])}</b><span>вознаграждения</span></div></section>"
        "<div class='two'><div class='panel'><h2>По направлениям</h2><div class='tablewrap'><table>"
        f"<tr><th>Направление</th><th>Кейсов</th><th>Заявок</th></tr>{dir_rows}</table></div></div>"
        "<div class='panel'><h2>По типу вознаграждения</h2><div class='tablewrap'><table>"
        f"<tr><th>Тип</th><th>Кейсов</th></tr>{reward_rows}</table></div>"
        "<h2>Этапы заявок</h2><div class='tablewrap'><table>"
        f"<tr><th>Этап</th><th>Заявок</th></tr>{status_rows}</table></div></div></div>"
        "<div class='panel'><h2>По компаниям</h2><div class='tablewrap'><table>"
        f"<tr><th>Компания</th><th>Кейсов</th><th>Заявок</th><th>Завершено</th></tr>{comp_rows}</table></div></div>"
    )
    return layout(ctx, "Аналитика", body)


def audit_page(ctx):
    allow_roles(ctx, "admin")
    action = (ctx.params.get("action") or "").strip()
    conn = db.connect()
    try:
        sql = ("SELECT a.*, u.username FROM audit_log a LEFT JOIN users u ON u.id=a.user_id")
        args = []
        if action:
            sql += " WHERE a.action=?"
            args.append(action)
        sql += " ORDER BY a.id DESC LIMIT 300"
        rows = conn.execute(sql, args).fetchall()
        actions = [r["action"] for r in conn.execute(
            "SELECT DISTINCT action FROM audit_log ORDER BY action").fetchall()]
    finally:
        conn.close()
    items = "".join(
        f"<tr><td>{esc(r['created_at'])}</td><td>{esc(r['username'] or 'система')}</td>"
        f"<td>{esc(r['action'])}</td><td>{esc(r['object_type'])}</td>"
        f"<td>{esc(r['object_id'] if r['object_id'] is not None else '')}</td>"
        f"<td>{esc(clip(r['details'], 120))}</td></tr>" for r in rows
    ) or "<tr><td colspan='6'>Записей нет.</td></tr>"
    body = (
        "<h1>Журнал действий</h1>"
        "<form class='filters' method='get' action='/audit'>"
        f"<select name='action'><option value=''>Все действия</option>{options(actions, action)}</select>"
        "<button>Показать</button></form>"
        "<div class='panel'><div class='tablewrap'><table>"
        "<tr><th>Время</th><th>Пользователь</th><th>Действие</th><th>Объект</th><th>ID</th><th>Детали</th></tr>"
        f"{items}</table></div></div>"
    )
    return layout(ctx, "Журнал действий", body)


# --------------------------------------------------------------------------
# Экспорт отчётов (CSV и Excel)
# --------------------------------------------------------------------------
def _csv_bytes(headers: list[str], rows: list[list]) -> bytes:
    import csv
    import io
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _xls_bytes(title: str, headers: list[str], rows: list[list]) -> bytes:
    cells = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for row in rows:
        body += "<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>"
    html_doc = (
        "<html><head><meta charset='utf-8'></head><body>"
        f"<h3>{esc(title)}</h3><table border='1'><tr>{cells}</tr>{body}</table></body></html>"
    )
    return html_doc.encode("utf-8")


def export_file(ctx, kind: str):
    """Возвращает (имя файла, байты, content-type)."""
    allow_roles(ctx, "admin")
    date_from, date_to = _period(ctx)
    conn = db.connect()
    try:
        if kind in ("applications", "analytics"):
            clauses, args = _period_sql("a.created_at", date_from, date_to)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = conn.execute(
                """SELECT a.id, c.title, co.name, u.full_name, u.institute, u.course,
                          a.status, a.project_status, a.score, a.place, a.payment_status, a.created_at
                   FROM applications a JOIN cases c ON c.id=a.case_id
                   JOIN companies co ON co.id=c.company_id JOIN users u ON u.id=a.student_id"""
                + where + " ORDER BY a.id", args,
            ).fetchall()
            headers = ["ID", "Кейс", "Компания", "Студент", "Институт", "Курс", "Решение",
                       "Этап", "Оценка", "Место", "Выплата", "Дата"]
            data = [list(r) for r in rows]
        elif kind == "cases":
            rows = conn.execute(
                """SELECT c.id, c.title, co.name, c.direction, c.difficulty, c.reward_type,
                          c.reward_amount, c.prize_fund, c.deadline, c.status, c.created_at
                   FROM cases c JOIN companies co ON co.id=c.company_id ORDER BY c.id"""
            ).fetchall()
            headers = ["ID", "Кейс", "Компания", "Направление", "Сложность", "Тип вознаграждения",
                       "Вознаграждение", "Призовой фонд", "Срок", "Статус", "Создан"]
            data = [list(r) for r in rows]
        elif kind == "students":
            rows = conn.execute(
                """SELECT u.id, u.full_name, u.email, u.institute, u.program, u.course, u.group_name,
                          u.skills, COUNT(a.id), AVG(a.score)
                   FROM users u LEFT JOIN applications a ON a.student_id=u.id
                   WHERE u.role='student' GROUP BY u.id ORDER BY u.id"""
            ).fetchall()
            headers = ["ID", "ФИО", "E-mail", "Институт", "Направление", "Курс", "Группа",
                       "Компетенции", "Заявок", "Средняя оценка"]
            data = [list(r) for r in rows]
        elif kind == "companies":
            rows = conn.execute(
                """SELECT co.id, co.name, co.industry, co.website, co.contacts, co.approved,
                          COUNT(DISTINCT c.id), COUNT(a.id)
                   FROM companies co LEFT JOIN cases c ON c.company_id=co.id
                   LEFT JOIN applications a ON a.case_id=c.id GROUP BY co.id ORDER BY co.id"""
            ).fetchall()
            headers = ["ID", "Компания", "Отрасль", "Сайт", "Контакты", "Подтверждена", "Кейсов", "Заявок"]
            data = [[*row[:5], "да" if row[5] else "нет", row[6], row[7]] for row in rows]
        else:
            raise HttpError(404, "Неизвестный отчёт.")
    finally:
        conn.close()

    stamp = now()[:10]
    titles = {
        "applications": "Заявки на кейсы", "analytics": "Отчёт по заявкам",
        "cases": "Кейсы", "students": "Студенты", "companies": "Компании",
    }
    title = titles.get(kind, kind)
    return title, headers, data


def export_response(ctx, filename: str):
    kind = filename.split(".")[0]
    ext = filename.split(".")[-1].lower()
    title, headers, data = export_file(ctx, kind)
    stamp = now()[:10]
    if ext == "csv":
        return f"{kind}-{stamp}.csv", _csv_bytes(headers, data), "text/csv; charset=utf-8"
    return f"{kind}-{stamp}.xls", _xls_bytes(title, headers, data), "application/vnd.ms-excel; charset=utf-8"

