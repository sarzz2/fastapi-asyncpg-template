# FastAPI Production-Ready Template

This is a production-ready template for building very efficient asynchronous web services with FastAPI. It includes a robust setup for database management with read-write splitting, background task processing with Celery, and a comprehensive suite of tools for code quality.

## Features

-   **Asynchronous Core**: Built with FastAPI and `asyncpg` for high-performance, non-blocking I/O.
-   **Scalable Database**: Out-of-the-box support for read-write splitting with PostgreSQL, including automatic health checks and failover for read replicas.
-   **Background Tasks**: Integrated Celery for handling long-running background jobs and scheduled tasks (Celery Beat) with async support.
-   **Custom Migration System**: A simple, script-based database migration tool (`migrate.py`) for managing schema changes.
-   **Centralized Configuration**: Environment-aware settings management using Pydantic.
-   **Code Quality Suite**: Pre-configured with `ruff`, `pylint`, and `mypy` for linting, formatting, and static type checking.
-   **Dependency Management**: Uses Poetry for clear, deterministic dependency management.

## Tech Stack

-   **Framework**: FastAPI
-   **Database**: PostgreSQL (via `asyncpg`)
-   **Task Queue**: Celery
-   **Broker & Backend**: Redis
-   **Dependency Management**: Poetry
-   **Linting & Formatting**: Ruff, Pylint
-   **Type Checking**: Mypy

---

## Getting Started

### Prerequisites

-   Python 3.12+
-   Poetry
-   PostgreSQL
-   Redis
-   LocalStack (for local AWS setup if you've AWS creds then no need of localstack)

### 1. Setup Environment

Create a `.env` file in the project root by copying the example file:

```bash
cp .env.example .env
```

Update the `.env` file with your local configuration.

### 2. Install Dependencies

Use Poetry to install the project dependencies.

```bash
poetry install
```

### 3. Run Database Migrations

Activate the virtual environment and run the migration script to set up your database schema.

```bash
poetry shell
python migrate.py
```

### 4. Setup pre-commit hooks

Pre-commit hooks ensure the code meets the project's quality standards before being pushed.

```bash
pre-commit install
```

To run hooks across the repo manually:

```bash
pre-commit run --all-files
```

---

## Development

### Running the FastAPI Application

To run the development server with live reloading:

```bash
uvicorn api.main:app --reload
```

or

```bash
fastapi dev api/main.py
```

The API will be available at `http://127.0.0.1:8000`.

Note: the project uses a lifespan manager (see `api/main.py`) to initialize resources like the database and Redis on startup. See the "Database" section below for details about DB initialization.

---

## Database Migrations

The project uses a custom migration script (`migrate.py`) to manage database schema changes.

**Create a New Migration:**

1.  Create a new SQL file in the `api/migrations/` directory. Use a timestamp-based name for ordering (e.g., `20240101120000_create_users_table.sql`).
2.  Structure the file with `-- up` and `-- down` sections.

    ```sql
    -- up
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) NOT NULL UNIQUE
    );

    -- down
    DROP TABLE users;
    ```

**Apply Migrations:**

```bash
python migrate.py up
```

**Rollback Migrations:**

To roll back the last migration:

```bash
python migrate.py down
```

To roll back the last 3 migrations:

```bash
python migrate.py down 3
```

To run a specific migration:

```bash
python migrate.py up/down -s migration_name
```

---

## Database (api/core/database.py)

Location: `api/core/database.py`

What it does:

-   Manages async PostgreSQL connection pools using `asyncpg` for both write (primary) and read (replica) databases.
-   Supports read-write splitting with per-region read pools, round-robin load balancing, health checks, and automatic failover.
-   Provides convenient async helpers used throughout the codebase:
    -   `DataBase.create_pool(write_uri, read_uris, ...)` — initialize pools
    -   `DataBase.fetch(...)`, `DataBase.fetchrow(...)`, `DataBase.fetchval(...)`, `DataBase.write(...)`, `DataBase.execute(...)` — query helpers
    -   `DataBase.get_pool_stats()` and `DataBase.health_check()` — runtime diagnostics
    -   `DataBase.close_pool()` — graceful shutdown
-   Exposes a FastAPI dependency `get_db()` (yields the `DataBase` class) for DI in route handlers and background tasks.

How to configure:

-   The project uses `api/core/config.py` (Pydantic settings). Important settings for DB behavior are:
    -   `PRIMARY_DATABASE_URL` — connection URL for the primary (write) DB
    -   `REPLICA_DATABASE_URL` — a replica/read URL (used in the example initialization)
    -   `HEALTH_CHECK_INTERVAL` — seconds between automatic health checks (0 to disable)
    -   `REGION_PRIORITY` — list of region names to prefer when routing reads

Initialization (example):
The app's lifespan in `api/main.py` already shows how the DB is initialized on startup. In short, call `DataBase.create_pool(...)` with your write and read URIs (for example, values from `settings.PRIMARY_DATABASE_URL` and `settings.REPLICA_DATABASE_URL`). On shutdown call `DataBase.close_pool()` to clean up connections.

Example snippet (taken from `api/main.py`):

```py
from api.core.database import DataBase
from api.core.config import settings

database_instance = DataBase()
await database_instance.create_pool(
        write_uri=settings.PRIMARY_DATABASE_URL,
        read_uris={"global": [settings.REPLICA_DATABASE_URL]},
)
# ...on shutdown
await database_instance.close_pool()
```

Notes and tips:

-   If you don't configure read replicas, the code will fall back to using the write pool for reads.
-   The DB implementation uses a custom `CustomRecord` (wrapping `asyncpg.Record`) to make conversion to Pydantic models simple and fast.
-   Health checks run in a background task (when `HEALTH_CHECK_INTERVAL > 0`) and update per-pool health/latency metrics that the routing logic uses to prefer healthy, low-latency pools.

### Running Celery Workers

To process background tasks, you need to run a Celery worker.

**1. Start the Worker:**

```bash
celery -A api.core.celery_app.celery_app worker --loglevel=info
```

**2. Start the Scheduler (Celery Beat):**

To run scheduled tasks (like log cleanup), start the Celery Beat service in a separate terminal.

```bash
celery -A api.core.celery_app.celery_app beat --loglevel=info
```

#### Async celery task example

```python
import logging
from typing import Any, List

from api.apps.user.v0.dao.user import UserDAO
from api.core.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(bind=True)
def list_all_users(self) -> List[dict[str, Any]]:
    """
    A Celery task that fetches a list of all users from the database.

    Returns:
        A list of user records as dictionaries.
    """
    # self.db and self.loop come from the AsyncBaseTask in celery_app.py
    user_dao = UserDAO(db=self.db)

    log.info("Executing task: list_all_users")
    # Use the task's event loop to run the async DAO method.
    records = self.loop.run_until_complete(user_dao.get_all_users())
    log.info("Fetched %d users from the database.", len(records))
    return [user.model_dump() for user in records]
```

## Code Quality

This project is configured with a suite of tools to ensure high code quality.

**Auto-format Code:**

```bash
poetry run ruff format
```

**Run All Checks:**

```bash
# Run linter
poetry run pylint .

# Run formatter and linter
poetry run ruff check .

# Run static type checker
poetry run mypy .
```
