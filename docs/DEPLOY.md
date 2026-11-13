# Развёртывание АИС «Витрина ИТ-проектов»

Документ описывает, как опубликовать систему в интернете, чтобы любой пользователь
(студент, компания, администратор) мог открыть её по обычной ссылке и работать
в браузере без установки чего-либо на свой компьютер.

Приложение — один процесс Python, который слушает порт и хранит данные в SQLite.
Этого достаточно для 100–500 активных пользователей и нагрузки вузовской витрины.

---

## Что понадобится

| Компонент | Зачем | Где взять |
|---|---|---|
| Сервер (VPS) 1 vCPU / 512 МБ RAM / 10 ГБ SSD | постоянно работающий процесс | Timeweb Cloud, Selectel, Yandex Cloud, Hetzner, Aeza и др. |
| Домен второго уровня | адрес вида `vitrina.uust.ru` | регистратор доменов или поддомен у ИТ-службы вуза |
| HTTPS-сертификат | требование ТЗ 7.2 | бесплатно через Caddy или Let's Encrypt (certbot) |
| Резервные копии | требование ТЗ 6.3 | cron + `sqlite3 .backup`, см. ниже |

Минимальные требования к серверу: Ubuntu 22.04/24.04, Docker (для варианта A)
или Python 3.10+ (для варианта B).

---

## Вариант A. VPS + Docker + Caddy (рекомендуется)

Caddy сам получает и продлевает HTTPS-сертификат — самый простой путь к «боевому»
адресу с шифрованием.

### 1. Подготовка сервера

```bash
ssh root@203.0.113.10

apt update && apt upgrade -y
# Docker
curl -fsSL https://get.docker.com | sh
# Caddy
apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy
```

### 2. Загрузка проекта

```bash
mkdir -p /opt/vitrina && cd /opt/vitrina
# скопируйте содержимое папки vitrina (git clone, scp или архив)
# например: scp -r ./vitrina/* root@203.0.113.10:/opt/vitrina/
```

### 3. Настройки (.env)

```bash
cp .env.example .env
nano .env
```

Обязательно измените:

```ini
DEMO_MODE=0                     # демо-данные не нужны на «боевой» установке
ADMIN_PASSWORD=СложныйПароль2026!
ADMIN_EMAIL=admin@uust.ru
COOKIE_SECURE=1                 # сайт будет работать по HTTPS
REGISTRATION_OPEN=1
```

### 4. Запуск

```bash
docker compose up -d --build
docker compose ps
curl -s http://127.0.0.1:8000/healthz   # {"status": "ok", ...}
```

Данные лежат в named volume `vitrina-data` (внутри — `/data/data.sqlite3` и `/data/uploads`).

### 5. Домен и HTTPS

В DNS-панели домена создайте запись:

```
A   vitrina.uust.ru   →   203.0.113.10
```

Затем `/etc/caddy/Caddyfile`:

```
vitrina.uust.ru {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
```

```bash
systemctl reload caddy
```

Через 1–2 минуты сайт откроется по адресу `https://vitrina.uust.ru`
с валидным сертификатом. Caddy продлевает его автоматически.

> Альтернатива — Nginx: готовый конфиг лежит в `deploy/nginx.conf`,
> сертификат выпускается командой `certbot --nginx -d vitrina.uust.ru`.

### 6. Обновление версии

```bash
cd /opt/vitrina
git pull                       # или замените файлы
docker compose up -d --build
```

База данных при обновлении не теряется: она в volume, а схема мигрируется
автоматически при старте.

---

## Вариант B. VPS без Docker: systemd + Nginx

Подходит, если на сервере политика запрещает контейнеры.

```bash
apt install -y python3 python3-venv nginx

useradd --system --home /opt/vitrina --shell /usr/sbin/nologin vitrina || true
mkdir -p /opt/vitrina /var/lib/vitrina
cp -r * /opt/vitrina/            # содержимое папки проекта
chown -R vitrina:vitrina /opt/vitrina /var/lib/vitrina

# systemd-юнит из проекта
cp /opt/vitrina/deploy/vitrina.service /etc/systemd/system/vitrina.service
systemctl daemon-reload
systemctl enable --now vitrina
systemctl status vitrina

# Nginx + HTTPS
cp /opt/vitrina/deploy/nginx.conf /etc/nginx/sites-available/vitrina
ln -s /etc/nginx/sites-available/vitrina /etc/nginx/sites-enabled/vitrina
nginx -t && systemctl reload nginx
certbot --nginx -d vitrina.uust.ru
```

Юнит уже задаёт `HOST=127.0.0.1`, `DATA_DIR=/var/lib/vitrina`, `COOKIE_SECURE=1`
и ограничения безопасности (`ProtectSystem`, `NoNewPrivileges`).

---

## Вариант C. Render (быстрое демо в интернете, бесплатно)

1. Зарегистрируйтесь на [render.com](https://render.com), подключите GitHub.
2. Загрузите проект в репозиторий GitHub.
3. В Render: **New → Blueprint**, выберите репозиторий — Render прочитает `render.yaml`.
4. Дождитесь сборки (2–3 минуты). Получите адрес вида
   `https://vitrina-it.onrender.com`.
5. Пароль администратора смотрите в переменных окружения сервиса
   (`ADMIN_PASSWORD` генерируется автоматически).

Ограничения бесплатного тарифа:
- сервис «засыпает» после 15 минут без запросов (первый запрос — 30–60 секунд);
- **нет постоянного диска**: база пересоздаётся при каждом переразвёртывании.
  Для сохранения данных включите платный план и блок `disk` в `render.yaml`.

---

## Вариант D. Railway (Railway.app)

1. Создайте проект → **Deploy from GitHub repo** (Railway сам найдёт `Dockerfile`).
2. Добавьте том: **Settings → Volumes → New Volume**, mount path `/data`.
3. В **Variables** задайте:
   `HOST=0.0.0.0`, `PORT=8000`, `DATA_DIR=/data`, `DEMO_MODE=0`,
   `ADMIN_PASSWORD=...`, `COOKIE_SECURE=1`.
4. **Settings → Networking → Generate Domain** — получите публичный HTTPS-адрес.

---

## Вариант E. Fly.io

```bash
fly auth login
fly launch --no-deploy          # использует fly.toml из проекта
fly volumes create vitrina_data --size 1 --region ams
fly secrets set ADMIN_PASSWORD='СложныйПароль2026!' DEMO_MODE=0
fly deploy
fly open                        # откроет https://vitrina-it.fly.dev
```

---

## Вариант F. Российские облачные провайдеры

Если данные должны размещаться в РФ (152-ФЗ), подойдут Timeweb Cloud, Selectel,
Yandex Cloud, VK Cloud. Схема одинаковая: создать виртуальную машину Ubuntu,
далее — **вариант A** или **B**.

- **Timeweb Cloud**: раздел «Приложения» умеет деплоить Docker-образ напрямую,
  переменные окружения задаются в панели, есть постоянные диски.
- **Yandex Cloud**: создайте ВМ, откройте 80/443 в Security Group, домен подключите
  через Yandex Cloud DNS.
- **Selectel**: ВМ + «Публичные IP», далее как в варианте A.

Для вузовской инфраструктуры часто требуется размещение на серверах заказчика
(ТЗ 1.6): тогда используйте вариант B и выдайте доступ через корпоративный VPN.

---

## Вариант G. Локальная сеть университета (без интернета)

Чтобы витрина была доступна в аудитории и компьютерном классе:

1. Назначьте компьютеру постоянный IP (например, `192.168.10.50`).
2. Запустите приложение с доступом из сети:
   ```bat
   set HOST=0.0.0.0
   set PORT=8000
   python app.py
   ```
3. Разрешите порт 8000 в брандмауэре:
   ```powershell
   New-NetFirewallRule -DisplayName "Vitrina IT" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
   ```
4. Студенты открывают `http://192.168.10.50:8000`.

Обратите внимание: в локальной сети без HTTPS пароли передаются открыто —
для постоянной работы нужен прокси с TLS (вариант A/B).

---

## Домен и DNS

| Запись | Значение | Когда нужна |
|---|---|---|
| `A` | IP сервера | домен второго уровня |
| `CNAME` | адрес платформы | Render/Railway/Fly (они сами выдают домен, можно привязать свой) |

Поддомен вуза (`vitrina.uust.ru`) обычно запрашивается в ИТ-службе; для него
достаточно записи `A` на IP сервера.

---

## Резервное копирование и обслуживание

Ежедневный бэкап базы (cron, запуск в 02:15):

```cron
15 2 * * * sqlite3 /var/lib/vitrina/data.sqlite3 ".backup '/var/backups/vitrina-$(date +\%F).sqlite3'" && find /var/backups -name 'vitrina-*.sqlite3' -mtime +30 -delete
45 2 * * * tar czf /var/backups/uploads-$(date +\%F).tar.gz -C /var/lib/vitrina uploads
```

Для Docker:

```bash
docker run --rm -v vitrina-data:/data -v /var/backups:/backup alpine \
  sh -c 'tar czf /backup/vitrina-$(date +%F).tar.gz -C /data .'
```

Восстановление:

```bash
systemctl stop vitrina
cp /var/backups/vitrina-2026-11-13.sqlite3 /var/lib/vitrina/data.sqlite3
systemctl start vitrina
```

Проверка состояния: `curl -s https://vitrina.uust.ru/healthz`.

---

## Чек-лист после развёртывания

- [ ] `https://<домен>/healthz` возвращает `{"status": "ok"}`;
- [ ] сертификат действителен, HTTP перенаправляется на HTTPS;
- [ ] `DEMO_MODE=0`, пароль администратора изменён с демонстрационного;
- [ ] вход администратора работает, в кабинете нет демо-кейсов;
- [ ] регистрация студента и компании проходит, компания появляется на модерации;
- [ ] публикация кейса, подача заявки и оценка выполняются (сценарий из README);
- [ ] загрузка файла результата работает, файл скачивается;
- [ ] экспорт CSV/Excel скачивается и открывается в Excel;
- [ ] журнал действий заполняется;
- [ ] резервная копия создаётся и восстанавливается;
- [ ] `DATA_DIR` указывает на постоянный диск (данные не теряются после перезапуска).

---

## Типичные проблемы

| Симптом | Причина и решение |
|---|---|
| `Не удалось запустить сервер ... 10048` | порт занят: `PORT=8080 python app.py` |
| Сайт открывается, но стили не грузятся | запросы к `/static/` блокирует прокси — проверьте `proxy_pass` |
| `attempt to write a readonly database` | каталог `DATA_DIR` недоступен для записи пользователю сервиса |
| После перезапуска пропали данные | `DATA_DIR` внутри контейнера без тома — подключите volume на `/data` |
| Вход не сохраняется по HTTPS | включите `COOKIE_SECURE=1` (и наоборот: при HTTP оставьте `0`) |
| Кириллица в CSV «кракозябрами» | откройте файл в Excel через «Данные → Из текста», кодировка UTF-8 (файл уже с BOM) |
| Компания не может создать кейс | компания не подтверждена администратором — `/dashboard` → «Подтвердить» |
