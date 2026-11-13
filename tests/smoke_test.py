"""Сквозные приёмочные тесты АИС «Витрина ИТ-проектов».

Запуск (из каталога проекта):
    python tests/smoke_test.py

Тест поднимает отдельный экземпляр приложения на свободном порту с временной
базой данных, проходит основные сценарии технического задания и завершает
работу с ненулевым кодом при первом же провале.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

passed = 0
failed: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed.append((name, detail))
        print(f"  FAIL {name} {detail}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Response:
    def __init__(self, status: int, headers, body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    @property
    def location(self) -> str:
        return self.headers.get("Location") or ""


class Client:
    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.raw = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), NoRedirect
        )

    def _request(self, method: str, path: str, body: bytes | None, content_type: str, follow: bool):
        request = urllib.request.Request(self.base + path, data=body, method=method)
        if content_type:
            request.add_header("Content-Type", content_type)
        opener = self.opener if follow else self.raw
        try:
            with opener.open(request, timeout=15) as response:
                return Response(response.status, response.headers, response.read())
        except urllib.error.HTTPError as error:
            return Response(error.code, error.headers, error.read())

    def get(self, path: str, follow: bool = True) -> Response:
        return self._request("GET", path, None, "", follow)

    def post(self, path: str, data: dict | None = None, follow: bool = True,
             files: dict | None = None) -> Response:
        fields = dict(data or {})
        if files:
            body, content_type = build_multipart(fields, files)
            return self._request("POST", path, body, content_type, follow)
        body = urllib.parse.urlencode(fields).encode()
        return self._request("POST", path, body, "application/x-www-form-urlencoded", follow)

    def csrf(self, path: str = "/dashboard") -> str:
        page = self.get(path)
        match = re.search(r"name='_csrf' value='([^']+)'", page.text)
        if not match:
            raise AssertionError(f"CSRF-токен не найден на {path} (статус {page.status})")
        return match.group(1)

    def login(self, username: str, password: str) -> Response:
        return self.post("/login", {"username": username, "password": password}, follow=False)


def build_multipart(fields: dict, files: dict):
    boundary = "----vitrina" + secrets.token_hex(8)
    chunks = []
    for key, value in fields.items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
        )
    for key, (filename, payload, mime) in files.items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n".encode()
        )
        chunks.append(payload)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_health(base: str, timeout: float = 25.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=2) as response:
                if response.status == 200 and json.loads(response.read())["status"] == "ok":
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("Сервер не запустился за отведённое время")


def main() -> int:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    # Данные теста кладём во временный каталог (в песочнице DSH запись
    # разрешена только в его корень, поэтому подкаталоги не используем).
    temp_root = Path(tempfile.gettempdir())
    token = secrets.token_hex(4)
    db_path = temp_root / f"vitrina-test-{token}.sqlite3"
    log_path = temp_root / f"vitrina-test-{token}.log"
    env = dict(os.environ)
    env.update({
        "DATA_DIR": str(temp_root),
        "DB_PATH": str(db_path),
        "UPLOAD_DIR": str(temp_root / f"vitrina-upload-{token}"),
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "DEMO_MODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(BASE_DIR),
    })
    (temp_root / f"vitrina-upload-{token}").mkdir(exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")
    process = subprocess.Popen([PYTHON, "app.py"], cwd=str(BASE_DIR), env=env,
                               stdout=log_file, stderr=subprocess.STDOUT)
    try:
        wait_health(base)
        run_scenarios(base)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        log_file.close()

    print()
    if failed:
        print("ПРОВАЛЕНО:", len(failed))
        for name, detail in failed:
            print(f" - {name} {detail}")
        print(f"\nЖурнал сервера: {log_path}")
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        print("\n".join(tail))
        return 1
    print(f"УСПЕШНО: {passed} проверок")
    return 0


def section(title: str) -> None:
    print(f"\n== {title} ==")


def run_scenarios(base: str) -> None:
    section("Публичная часть")
    anonymous = Client(base)
    home = anonymous.get("/")
    check("главная страница доступна", home.status == 200 and "Витрина" in home.text)
    check("карточки кейсов выводятся", home.text.count("<article class='card'>") >= 5)
    check("завершённый кейс виден на витрине", "Чат-бот поддержки студентов" in home.text)
    check("на карточке кейса видны победители",
          "Результаты и победители" in anonymous.get("/case/8").text)
    check("проекты студентов доступны", "Проекты студентов" in anonymous.get("/projects").text)
    check("рейтинг доступен", "Рейтинг студентов" in anonymous.get("/rating").text)
    check("карточка компании доступна", anonymous.get("/company/1").status == 200)
    check("карточка студента доступна", anonymous.get("/student/5").status == 200)
    check("страница входа доступна", "Демо" in anonymous.get("/login").text)
    check("страница регистрации доступна", "Регистрация" in anonymous.get("/register").text)
    check("несуществующая страница — 404", anonymous.get("/no-such-page").status == 404)
    check("healthcheck работает",
          json.loads(anonymous.get("/healthz").body)["status"] == "ok")

    section("Статика и защита от обхода каталогов")
    check("style.css отдаётся", anonymous.get("/static/style.css").status == 200)
    check("app.css отдаётся", anonymous.get("/static/app.css").status == 200)
    for path in ("/static/../app.py", "/static/%2e%2e/app.py", "/static/../../README.txt",
                 "/static/..%5capp.py"):
        check(f"обход каталога закрыт: {path}", anonymous.get(path).status == 404)

    section("Авторизация и роли")
    admin = Client(base)
    response = admin.login("admin", "Admin12345!")
    check("вход администратора", response.status == 303 and "/dashboard" in response.location)
    check("кабинет администратора", "Администрирование" in admin.get("/dashboard").text)

    bad = Client(base)
    response = bad.login("admin", "wrong-password")
    check("неверный пароль отклонён", response.status == 303 and "err=login" in response.location)

    student = Client(base)
    check("вход студента", student.login("student01", "Student123!").status == 303)
    dashboard = student.get("/dashboard").text
    check("кабинет студента", "Личный кабинет студента" in dashboard)
    check("заявки студента видны", "Чат-бот поддержки студентов" in dashboard)

    company = Client(base)
    check("вход компании", company.login("company", "Company123!").status == 303)
    check("кабинет компании", "Кабинет компании" in company.get("/dashboard").text)

    section("Защита форм (CSRF)")
    check("POST без CSRF-токена отклонён", student.post("/profile", {"full_name": "Хакер"}).status == 403)
    token = student.csrf()
    saved = student.post("/profile", {"_csrf": token, "full_name": "Иванов Иван Иванович",
                                      "email": "student01@uust.ru", "skills": "Python, SQL"},
                         follow=False)
    check("POST с CSRF-токеном принят", saved.status == 303 and "msg=saved" in saved.location)

    section("Подача заявки и избранное")
    token = student.csrf("/case/3")
    applied = student.post("/case/3/apply", {
        "_csrf": token, "message": "Хочу участвовать в кейсе по ИБ",
        "portfolio_url": "https://github.com/example", "github_url": "https://github.com/example",
    }, follow=False)
    check("заявка подана", applied.status == 303 and "msg=applied" in applied.location)
    duplicate = student.post("/case/3/apply", {"_csrf": token, "message": "Ещё раз"}, follow=False)
    check("повторная заявка отклонена", "err=already_applied" in duplicate.location)
    student.post("/case/1/favorite", {"_csrf": token}, follow=False)
    check("избранное работает", "Избранные кейсы" in student.get("/dashboard").text)

    section("Витрина: поиск и фильтры")
    filtered = anonymous.get("/?reward=" + urllib.parse.quote("Конкурсный")).text
    check("фильтр по типу вознаграждения применён", "Сервис интеллектуального поиска" in filtered)
    check("фильтр исключает другие типы", "Мобильный кабинет студента" not in filtered)
    search = anonymous.get("/?q=" + urllib.parse.quote("Python")).text
    check("поиск по технологиям работает", "Сервис интеллектуального поиска" in search)
    check("фильтр по стажировке работает",
          "Сервис интеллектуального поиска" in anonymous.get("/?internship=1").text)

    section("Создание и модерация кейса")
    token = company.csrf("/case/new")
    created = company.post("/case/new", {
        "_csrf": token, "title": "Кейс приёмочного теста", "short_description": "Короткое описание",
        "description": "Полное описание задачи для теста", "direction": "Backend",
        "technologies": "Python, SQLite", "difficulty": "Средний",
        "participation_format": "Командный", "work_format": "Дистанционный",
        "team_size": "3", "deadline": "2027-01-31", "reward_type": "Образовательный",
        "reward_amount": "0", "prize_fund": "0", "rights_mode": "Результаты остаются у авторов",
    }, follow=False)
    check("кейс создан", created.status == 303 and "msg=case_created" in created.location)
    admin_dashboard = admin.get("/dashboard").text
    check("кейс виден в модерации", "Кейс приёмочного теста" in admin_dashboard)
    new_case_id = int(re.search(r"/admin/case/(\d+)'", admin_dashboard).group(1))
    token = admin.csrf()
    published = admin.post(f"/admin/case/{new_case_id}", {"_csrf": token, "status": "Опубликован"},
                           follow=False)
    check("кейс опубликован", published.status == 303)
    check("кейс виден на витрине", "Кейс приёмочного теста" in anonymous.get("/").text)
    check("черновик кейса скрыт от чужих",
          anonymous.get("/case/6").status == 404)

    section("Заявки: принятие, команда, результат")
    page = company.get(f"/case/{new_case_id}/applications")
    check("страница заявок компании доступна", page.status == 200)
    token = company.csrf()
    student_id = 5
    applied = student.post(f"/case/{new_case_id}/apply", {
        "_csrf": student.csrf(f"/case/{new_case_id}"), "message": "Готов выполнить кейс",
    }, follow=False)
    check("заявка на новый кейс подана", applied.status == 303)
    page = company.get(f"/case/{new_case_id}/applications").text
    application_id = int(re.search(r"/application/(\d+)/update", page).group(1))
    accepted = company.post(f"/application/{application_id}/update", {
        "_csrf": token, "status": "Принята", "project_status": "Выполняется",
        "score": "90", "place": "1 место", "review": "Отличная работа",
        "payment_status": "Ожидается",
    }, follow=False)
    check("заявка принята и оценена", accepted.status == 303)
    check("студент видит оценку", "1 место" in student.get("/dashboard").text)
    check("уведомление отправлено", "Уведомления" in student.get("/notifications").text)

    token = company.csrf()
    team = company.post(f"/case/{new_case_id}/team", {
        "_csrf": token, "name": "Команда теста", "mentor": "Наставник",
        "member": str(student_id), f"role_{student_id}": "Team Lead",
    }, follow=False)
    check("команда сформирована", team.status == 303)
    workspace = student.get(f"/case/{new_case_id}/workspace")
    check("рабочая страница доступна участнику", workspace.status == 200)
    check("состав команды отображается", "Команда теста" in workspace.text)

    token = student.csrf(f"/case/{new_case_id}/workspace")
    result = student.post(f"/application/{application_id}/result", {
        "_csrf": token, "result_url": "https://github.com/example/result",
        "result_note": "Результат готов",
    }, files={"result_file": ("report.txt", b"it works", "text/plain")}, follow=False)
    check("результат отправлен с файлом", result.status == 303 and "msg=result_saved" in result.location)
    page = company.get(f"/case/{new_case_id}/applications").text
    check("компания видит результат", "Результат готов" in page)
    check("вложение доступно компании", company.get(
        "/file/" + re.search(r"/file/(\d+)", page).group(1)).status == 200)
    check("вложение закрыто для анонима", anonymous.get(
        "/file/" + re.search(r"/file/(\d+)", page).group(1)).status == 404)

    section("Редактирование кейса и контрольные точки")
    token = company.csrf(f"/case/{new_case_id}/edit")
    check("страница редактирования кейса доступна", "Редактирование кейса" in company.get(
        f"/case/{new_case_id}/edit").text)
    edited = company.post(f"/case/{new_case_id}/edit", {
        "_csrf": token, "title": "Кейс приёмочного теста", "short_description": "Короткое описание",
        "description": "Обновлённое полное описание", "direction": "Backend",
        "technologies": "Python, SQLite, Docker", "difficulty": "Средний",
        "participation_format": "Командный", "work_format": "Дистанционный",
        "team_size": "4", "deadline": "2027-02-15", "reward_type": "Образовательный",
        "reward_amount": "0", "prize_fund": "0", "rights_mode": "Результаты остаются у авторов",
    }, follow=False)
    check("кейс отредактирован и отправлен на модерацию",
          edited.status == 303 and "msg=case_updated" in edited.location)
    admin.post(f"/admin/case/{new_case_id}", {"_csrf": admin.csrf(), "status": "Опубликован"},
               follow=False)
    check("кейс опубликован повторно", "Кейс приёмочного теста" in anonymous.get("/").text)
    token = company.csrf(f"/case/{new_case_id}/workspace")
    added = company.post(f"/case/{new_case_id}/stage", {
        "_csrf": token, "title": "Тестовый этап", "due_date": "2027-02-01",
        "description": "Описание этапа",
    }, follow=False)
    check("этап добавлен", added.status == 303)
    workspace_page = company.get(f"/case/{new_case_id}/workspace").text
    check("этап виден на рабочей странице", "Тестовый этап" in workspace_page)
    stage_id = re.search(r"/stage/(\d+)/update", workspace_page).group(1)
    token = company.csrf(f"/case/{new_case_id}/workspace")
    updated = company.post(f"/stage/{stage_id}/update", {"_csrf": token, "status": "Выполнена"},
                           follow=False)
    check("статус этапа обновлён", updated.status == 303)
    check("готовность этапов отображается",
          "готовность этапов" in company.get(f"/case/{new_case_id}/workspace").text)

    section("Карточка компании")
    token = company.csrf()
    saved = company.post("/company/profile", {
        "_csrf": token, "name": "ООО «Цифровые решения»", "short_name": "Цифровые решения",
        "industry": "ИТ / разработка ПО", "website": "https://example.ru",
        "contacts": "projects@example.ru", "description": "Обновлённое описание компании",
    }, follow=False)
    check("карточка компании сохраняется", saved.status == 303 and "msg=saved" in saved.location)
    check("изменения видны публично", "Обновлённое описание компании" in anonymous.get("/company/1").text)

    section("Регистрация и модерация компании")
    new_student = Client(base)
    registered = new_student.post("/register", {
        "role": "student", "username": "test_student", "password": "Passw0rd!",
        "password2": "Passw0rd!", "full_name": "Тестов Тест Тестович",
        "email": "test@uust.ru", "consent": "1", "skills": "Go, Docker",
    }, follow=False)
    check("регистрация студента", registered.status == 303 and "msg=registered" in registered.location)
    check("новый студент входит", new_student.login("test_student", "Passw0rd!").status == 303)

    new_company = Client(base)
    registered = new_company.post("/register", {
        "role": "company", "username": "test_company", "password": "Passw0rd!",
        "password2": "Passw0rd!", "full_name": "ООО Тест", "email": "hr@test.ru",
        "consent": "1", "company_name": "ООО «Тестовая компания»", "industry": "ИТ",
    }, follow=False)
    check("регистрация компании", registered.status == 303 and "msg=registered_company" in registered.location)
    new_company.login("test_company", "Passw0rd!")
    check("компания без подтверждения не создаёт кейс",
          "Компания на проверке" in new_company.get("/case/new").text)
    dashboard = admin.get("/dashboard").text
    pending_company_id = int(re.search(r"/admin/company/(\d+)", dashboard).group(1))
    token = admin.csrf()
    approved = admin.post(f"/admin/company/{pending_company_id}", {"_csrf": token, "approved": "1"},
                          follow=False)
    check("компания подтверждена", approved.status == 303)
    check("подтверждённая компания видит форму кейса", "Новый ИТ-кейс" in new_company.get("/case/new").text)

    section("Поиск студентов и приглашения")
    check("поиск студентов доступен компании", "Поиск студентов" in company.get("/students").text)
    found = company.get("/students?q=Python").text
    check("поиск по компетенциям находит студента", "Иванов" in found)
    token = company.csrf("/students")
    invited = company.post("/invite", {
        "_csrf": token, "student_id": "7", "case_id": "1", "message": "Приглашаем в команду",
    }, follow=False)
    check("приглашение отправлено", invited.status == 303 and "msg=invited" in invited.location)
    student3 = Client(base)
    student3.login("student03", "Student123!")
    check("студент видит приглашение", "приглашает вас" in student3.get("/dashboard").text)
    token = student3.csrf()
    accepted = student3.post("/invitation/2/respond", {"_csrf": token, "action": "accept"}, follow=False)
    check("приглашение принято", accepted.status == 303)

    section("Аналитика, отчёты, журнал")
    check("аналитика доступна", "Аналитика и отчёты" in admin.get("/analytics").text)
    period = admin.get("/analytics?from=2020-01-01&to=2030-01-01")
    check("аналитика с периодом", period.status == 200)
    csv_report = admin.get("/export/applications.csv")
    check("экспорт CSV", csv_report.status == 200 and csv_report.body.startswith("\ufeff".encode()))
    check("CSV содержит данные", "Кейс" in csv_report.text and "\n" in csv_report.text)
    xls_report = admin.get("/export/cases.xls")
    check("экспорт Excel", xls_report.status == 200 and "<table" in xls_report.text)
    check("экспорт студентов", admin.get("/export/students.csv").status == 200)
    check("экспорт компаний", admin.get("/export/companies.csv").status == 200)
    check("экспорт аналитики в Excel", admin.get("/export/analytics.xls").status == 200)
    check("экспорт запрещён студенту", student.get("/export/applications.csv").status == 403)
    check("журнал действий доступен", "Журнал действий" in admin.get("/audit").text)
    check("действия зафиксированы", "login" in admin.get("/audit?action=login").text)

    section("Ограничение попыток входа")
    brute = Client(base)
    for _ in range(10):
        brute.login("student02", "wrong")
    limited = brute.login("student02", "Student123!")
    check("подбор пароля ограничен", limited.status == 303 and "err=rate" in limited.location)

    section("Блокировка пользователя")
    dashboard = admin.get("/dashboard").text
    token = admin.csrf()
    blocked = admin.post("/admin/user/8", {"_csrf": token, "blocked": "1"}, follow=False)
    check("пользователь заблокирован", blocked.status == 303)
    blocked_client = Client(base)
    response = blocked_client.login("student04", "Student123!")
    check("заблокированный не входит", "err=blocked" in response.location)
    admin.post("/admin/user/8", {"_csrf": admin.csrf(), "blocked": "0"}, follow=False)

    section("Ограничения прав и NDA")
    check("студент не может модерировать кейс",
          student.post(f"/admin/case/{new_case_id}", {"_csrf": token, "status": "Скрыт"}).status == 403)
    check("компания не может открыть чужой кейс",
          company.get("/case/4/applications").status in (403, 404))
    nda_page = anonymous.get("/case/4").text
    check("NDA скрывает полное ТЗ", "NDA" in nda_page and "Полное описание скрыто" in nda_page)

    section("Экранирование HTML")
    token = company.csrf("/case/new")
    company.post("/case/new", {
        "_csrf": token, "title": "<script>alert('xss')</script>", "short_description": "<b>злой</b>",
        "description": "x", "direction": "Backend",
    }, follow=False)
    listing = anonymous.get("/").text
    check("HTML в названии экранирован", "<script>alert('xss')</script>" not in listing)

    section("Выход из системы")
    check("выход выполняется", student.get("/logout", follow=False).status == 303)
    check("после выхода кабинет недоступен",
          "/login" in student.get("/dashboard", follow=False).location)


if __name__ == "__main__":
    sys.exit(main())
