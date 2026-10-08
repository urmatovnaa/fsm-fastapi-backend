# 🚀 MasterFlow — Field Service Management (FSM) System

**MasterFlow** — асинхронная веб-система для автоматизации процессов выездного обслуживания, управления заявками, распределения мастеров и учета складских запасов.

---

## 🛠 Технологический стек

* **Backend:** Python 3.11+, FastAPI, Pydantic v2
* **Database:** PostgreSQL, SQLAlchemy 2.0 (AsyncIO), Alembic
* **Infrastructure:** Docker, Docker Compose
* **Architecture:** Modular Monolith (Clean Architecture principles)

---

## 📁 Структура проекта

```text
MasterFlow/
├── alembic/              # Скрипты и конфигурации миграций БД
├── app/
│   ├── api/              # Маршрутизация и API эндпоинты
│   │   └── v1/           # Версионирование API (control, execution, planning)
│   ├── core/             # Конфигурации, подключение к БД, безопасность
│   ├── models/           # SQLAlchemy модели (ORM)
│   └── schemas/          # Pydantic схемы (валидация данных)
├── .env.example          # Шаблон переменных окружения
├── docker-compose.yml    # Контейнеризация сервисов (PostgreSQL)
├── requirements.txt      # Зависимости проекта
└── main.py               # Точка входа в приложение FastAPI

```

## 🚀 Быстрый запуск

### 1. Клонирование репозитория

```bash
git clone git@github.com:ВАШ_ЛОГИН/masterflow-backend.git
cd masterflow-backend

```

### 2. Настройка виртуального окружения

```bash
# Создание venv
python -m venv venv

# Активация venv (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Активация venv (Linux/macOS)
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt

```

### 3. Переменные окружения

Создайте файл `.env` на основе шаблона `.env.example`:

```bash
# В Windows PowerShell:
Copy-Item .env.example .env

# В Bash / Linux:
cp .env.example .env

```

Пример содержимого `.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgrespassword@localhost:5432/masterflow_db

```

### 4. Запуск базы данных в Docker

```bash
docker compose up -d

```

### 5. Применение миграций БД

```bash
alembic upgrade head

```

### 6. Запуск сервера разработки

```bash
uvicorn app.main:app --reload

```

Приложение будет доступно по адресу: `http://127.0.0.1:8000`

---

## 📚 Документация API

После запуска сервера интерактивная документация доступна по адресам:

* **Swagger UI:** `http://127.0.0.1:8000/docs`
* **ReDoc:** `http://127.0.0.1:8000/redoc`

---

## 👥 Командная разработка и ролевая модель

Проект разрабатывается командой из 3 человек со следующим разделением модулей:

1. **Склад, Учет и Аналитика (`/control`)** — базовые сущности БД, запчасти, инвентаризация, отчетность.
2. **Ядро Backend и Наряды (`/execution`)** — авторизация, жизненный цикл заявок, интерфейсы мастеров.
3. **Планирование и Гео-сервисы (`/planning`)** — слоты времени, гео-распределение, алгоритмы автоназначения.

```

```