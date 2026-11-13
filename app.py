"""АИС «Витрина ИТ-проектов» — точка входа and HTTP-сервер.

Запуск:  python app.py            (http://127.0.0.1:8000)
Сброс демо-базы: python app.py --reset-demo
"""
from __future__ import annotations

import re
import secrets
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import core
import db
import views
from core import APP_VERSION, HOST, PORT, STATIC_DIR, UPLOAD_DIR, HttpError, Redirect, esc, parse_request

GET_ROUTES = [
    (r"^/$", views.home),
    (r"^/login$", views.login_page),
    (r"^/register$", views.register_page),
    (r"^/logout$", views.logout),
    (r"^/projects$", views.projects),
    (r"^/project/(\d+)$", views.project_detail),
    (r"^/student/(\d+)$", views.portfolio),
    (r"^/rating$", views.rating_page),
    (r"^/company/(\d+)$", views.company_page),
    (r"^/case/new$", views.case_form),
    (r"^/case/(\d+)/edit$", views.case_edit),
    (r"^/case/(\d+)/applications$", views.applications_page),
    (r"^/case/(\d+)/workspace$", views.workspace),
    (r"^/case/(\d+)$", views.case_detail),
    (r"^/dashboard$", None),
    (r"^/my-projects$", views.my_projects),
    (r"^/students$", views.students_search),
    (r"^/notifications$", views.notifications),
    (r"^/analytics$", views.analytics_page),
    (r"^/audit$", views.audit_page),
]

POST_ROUTES = [
    (r"^/login$", views.login_submit),
    (r"^/register$", views.register_submit),
    (r"^/profile$", views.profile_save),
    (r"^/password$", views.password_change),
    (r"^/company/profile$", views.company_profile_save),
    (r"^/case/new$", views.case_create),
    (r"^/case/(\d+)/edit$", views.case_update),
    (r"^/case/(\d+)/apply$", views.case_apply),
    (r"^/case/(\d+)/favorite$", views.favorite_toggle),
    (r"^/case/(\d+)/team$", views.team_create),
    (r"^/case/(\d+)/stage$", views.stage_add),
    (r"^/case/(\d+)/comment$", views.comment_add),
    (r"^/application/(\d+)/update$", views.application_update),
    (r"^/application/(\d+)/result$", views.result_submit),
    (r"^/stage/(\d+)/update$", views.stage_update),
    (r"^/invitation/(\d+)/respond$", views.invitation_respond),
    (r"^/invite$", views.invite_student),
    (r"^/project/new$", views.project_new),
    (r"^/admin/case/(\d+)$", views.admin_case_status),
    (r"^/admin/company/(\d+)$", views.admin_company_status),
    (r"^/admin/user/(\d+)$", views.admin_user_block),
]

PARAM_NAMES = {
    "case": ("cid",),
    "project": ("pid",),
    "student": ("student_id",),
    "company": ("company_id",),
    "application": ("aid",),
    "invitation": ("iid",),
    "stage": ("sid",),
    "user": ("user_id",),
}

STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
}


def dashboard(ctx):
    if not ctx.user:
        raise Redirect("/login")
    if ctx.user["role"] == "student":
        return views.student_dashboard(ctx)
    if ctx.user["role"] == "company":
        return views.company_dashboard(ctx)
    return views.admin_dashboard(ctx)


def param_name_for(pattern: str, index: int) -> str:
    for key, names in PARAM_NAMES.items():
        if f"/{key}/" in pattern:
            return names[index - 1] if index - 1 < len(names) else f"p{index}"
    return f"p{index}"


def error_page(ctx, status: int, message: str, detail: str = "") -> str:
    detail_html = ""
    if detail:
        detail_html = "<p class='muted'>" + esc(detail) + "</p>"
    body = (
        "<div class='panel error'><h1>Ошибка " + str(status) + "</h1>"
        f"<p>{esc(message)}</p>{detail_html}"
        "<p><a class='button' href='/'>На главную</a> "
        "<a class='button secondary' href='javascript:history.back()'>Назад</a></p></div>"
    )
    try:
        return views.layout(ctx, "Ошибка", body)
    except Exception:
        return f"<!doctype html><meta charset='utf-8'><h1>{status}</h1><p>{esc(message)}</p>"


class Handler(BaseHTTPRequestHandler):
    server_version = "Vitrina/" + APP_VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # ------------------------------------------------------------------
    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method: str):
        ctx = views.Ctx(None, None, {}, {}, {}, "", "")
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            params = {key: ",".join(values) for key, values in query.items()}
            ctx.params = params
            ctx.ip = core.client_ip(self)

            if path.startswith("/static/"):
                return self.serve_static(path)
            if path == "/healthz":
                return self.serve_health()
            if path.startswith("/file/"):
                return self.serve_upload(path, params)

            sid = core.cookie_value(self, "sid")
            session, user = db.load_session(sid)
            ctx.session, ctx.user, ctx.sid = session, user, sid

            if method == "POST":
                form, files = parse_request(self)
                ctx.form, ctx.files = form, files
                if session and path not in ("/login", "/register"):
                    token = form.get("_csrf") or self.headers.get("X-CSRF-Token") or ""
                    if not core.secrets.compare_digest(str(token), str(session["csrf"])):
                        raise HttpError(403, views.ERRORS["csrf"])

            routes = GET_ROUTES if method == "GET" else POST_ROUTES
            for pattern, view in routes:
                match = re.match(pattern, path)
                if not match:
                    continue
                for index, value in enumerate(match.groups(), start=1):
                    if value is not None:
                        ctx.params[param_name_for(pattern, index)] = value
                if view is None:
                    view = dashboard
                html = view(ctx)
                if html is None:
                    raise HttpError(404, "Страница не найдена.")
                return self.send_html(html)

            if path.startswith("/export/"):
                filename = path[len("/export/"):]
                if not re.fullmatch(r"[a-z]+\.(csv|xls)", filename):
                    raise HttpError(404, "Отчёт не найден.")
                name, payload, content_type = views.export_response(ctx, filename)
                return self.send_download(name, payload, content_type)

            raise HttpError(404, "Страница не найдена.")

        except views.RedirectWithCookie as redirect:
            return self.send_redirect(redirect.url, getattr(redirect, "cookie", None))
        except Redirect as redirect:
            return self.send_redirect(redirect.url)
        except HttpError as error:
            self.close_connection = True
            self.send_html(error_page(ctx, error.status, error.message), error.status)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            traceback.print_exc()
            self.close_connection = True
            message = "Внутренняя ошибка сервера. Попробуйте позже."
            try:
                self.send_html(error_page(ctx, 500, message, f"Код обращения: {APP_VERSION}"), 500)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def send_html(self, content: str, status: int = 200, extra_headers: dict | None = None):
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_redirect(self, url: str, cookie: str | None = None):
        self.send_response(303)
        self.send_header("Location", url)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_download(self, filename: str, payload: bytes, content_type: str):
        from urllib.parse import quote
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Disposition",
                         f"attachment; filename*=UTF-8''{quote(filename)}")
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    # ------------------------------------------------------------------
    def serve_static(self, path: str):
        rel = urllib.parse.unquote(path[len("/static/"):])
        if not rel or ".." in rel or rel.startswith("/") or "\\" in rel:
            raise HttpError(404, "Файл не найден.")
        target = (STATIC_DIR / rel).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            raise HttpError(404, "Файл не найден.")
        suffix = target.suffix.lower()
        if suffix not in STATIC_TYPES or not target.is_file():
            raise HttpError(404, "Файл не найден.")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES[suffix])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def serve_health(self):
        import json
        payload = {"status": "ok", "version": APP_VERSION}
        try:
            conn = db.connect()
            conn.execute("SELECT 1").fetchone()
            conn.close()
        except Exception as exc:  # pragma: no cover
            payload = {"status": "error", "detail": str(exc)[:200]}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200 if payload["status"] == "ok" else 503)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_upload(self, path: str, params: dict):
        sid = core.cookie_value(self, "sid")
        session, user = db.load_session(sid)
        if not user:
            raise HttpError(404, "Файл не найден.")
        file_id = path[len("/file/"):]
        if not file_id.isdigit():
            raise HttpError(404, "Файл не найден.")
        conn = db.connect()
        try:
            row = conn.execute("SELECT * FROM files WHERE id=?", (int(file_id),)).fetchone()
            if not row:
                raise HttpError(404, "Файл не найден.")
            allowed = row["user_id"] == user["id"] or user["role"] == "admin"
            if not allowed and row["case_id"]:
                allowed = bool(conn.execute(
                    "SELECT 1 FROM cases c JOIN companies co ON co.id=c.company_id"
                    " WHERE c.id=? AND co.owner_user_id=?", (row["case_id"], user["id"])).fetchone())
            if not allowed and row["case_id"]:
                allowed = bool(conn.execute(
                    """SELECT 1 FROM applications a WHERE a.case_id=? AND a.student_id=?
                       AND a.status='Принята'""", (row["case_id"], user["id"])).fetchone())
        finally:
            conn.close()
        if not allowed:
            raise HttpError(403, "Нет доступа к файлу.")
        target = UPLOAD_DIR / row["stored_name"]
        if not target.is_file():
            raise HttpError(404, "Файл не найден на диске.")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", row["content_type"] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition",
                         "attachment; filename*=UTF-8''" + urllib.parse.quote(row["original_name"]))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    if "--reset-demo" in sys.argv:
        db.reset_db()
        print("Демонстрационная база данных сброшена и заполнена заново.")
        return 0
    if "--version" in sys.argv:
        print(f"АИС «Витрина ИТ-проектов» {APP_VERSION}")
        return 0
    db.init_db()
    try:
        httpd = Server((HOST, PORT), Handler)
    except OSError as exc:
        print(f"Не удалось запустить сервер на {HOST}:{PORT}: {exc}")
        print("Проверьте, не занят ли порт, или задайте другой: PORT=8080 python app.py")
        return 1
    local = "127.0.0.1" if HOST in ("0.0.0.0", "") else HOST
    print(f"АИС «Витрина ИТ-проектов» {APP_VERSION}")
    print(f"Сервер запущен: http://{local}:{PORT}")
    print(f"База данных: {core.DB_PATH}")
    print("Демо-режим: " + ("включён" if core.DEMO_MODE else "выключен"))
    print("Остановка: Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
