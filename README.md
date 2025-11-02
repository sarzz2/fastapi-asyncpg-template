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

Update the `.env` file with your local configuration. The default values are configured to work with the provided `docker-compose.yml`.

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

Pre commit hooks makes sure the code alwyas meets the best practices before being pushed.

```bash
pre-commit install
```

To run hooks before commiting

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
