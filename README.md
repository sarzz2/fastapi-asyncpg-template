# FastAPI Production-Ready Template

This is a production-ready template for building very efficient asynchronous web services with FastAPI. It includes a robust setup for database management with read-write splitting, background task processing with Celery, and a comprehensive suite of tools for code quality.

This project also includes a performance profiler using `pyinstrument` to help you identify and optimize performance bottlenecks.
To see the profiler in action, add the `profile=true` query parameter to any request. For example: `http://localhost:8000/health?profile=true`.

For error monitoring sentry is used
Add your sentry dsn in the .env file

## Features

- **Asynchronous Core**: Built with FastAPI and `asyncpg` for high-performance, non-blocking I/O.
- **Scalable Database**: Out-of-the-box support for read-write splitting with PostgreSQL, including automatic health checks and failover for read replicas.
- **Background Tasks**: Integrated Celery for handling long-running background jobs and scheduled tasks (Celery Beat) with async support.
- **Custom Migration System**: A simple, script-based database migration tool (`migrate.py`) for managing schema changes.
- **Centralized Configuration**: Environment-aware settings management using Pydantic.
- **Code Quality Suite**: Pre-configured with `ruff`, `pylint`, and `mypy` for linting, formatting, and static type checking.
- **Dependency Management**: Uses uv for lightning-fast, deterministic dependency management.

## Tech Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL (via `asyncpg`)
- **Task Queue**: Celery
- **Broker & Backend**: Redis
- **Dependency Management**: uv
- **Linting & Formatting**: Ruff, Pylint
- **Type Checking**: Mypy

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Development](#development)
- [Database Migrations](#database-migrations)
- [Database Core](#database-apicoredatabasepy)
- [User Management & Authentication](#user-management--authentication)
- [AWS S3 Integration](#aws-s3-integration)
- [Notification System](#notification-system)
- [Event Bus](#event-bus)
- [Code Quality](#code-quality)

---

## Getting Started

### Prerequisites

- Python 3.12+
- uv
- PostgreSQL17+
- Redis
- LocalStack (for local AWS setup if you've AWS creds then no need of localstack)

### 1. Setup Environment

Create a `.env` file in the project root by copying the example file:

```bash
cp .env.example .env
```

Update the `.env` file with your local configuration.

### 2. Install Dependencies

Use uv to install the project dependencies.

```bash
uv sync
```

### 3. Install DB extensions Run Database Migrations

Using 2 extensions

```bash
brew install pgxnclient
pgxn install pg_uuidv7 --pg_config /opt/homebrew/opt/postgresql@17/bin/pg_config
brew services restart postgresql@17
```

Activate the virtual environment and run the migration script to set up your database schema.

```bash
uv run python migrate.py
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

## Dockerization

You can run the entire application stack (API, Postgres, Redis, Celery, LocalStack) using Docker Compose.

### Prerequisites

- Docker
- Docker Compose

### Running with Docker

1.  **Build and Start Services:**

    ```bash
    docker-compose up --build
    ```

2.  **Access the Application:**

    The API will be available at `http://localhost:8000`.

3.  **Services:**
    - **api**: The FastAPI application.
    - **postgres**: PostgreSQL database (Primary).
    - **redis**: Redis for caching and Celery broker.
    - **celery_worker**: Background task worker.
    - **celery_beat**: Scheduled task scheduler.
    - **localstack**: AWS S3 emulation for local development.

4.  **Persistent Data:**
    - Database data is persisted in the `postgres_data` volume.
    - LocalStack data (S3 buckets) is persisted in the `localstack_data` volume.

---

## Development

### Running the FastAPI Application

To run the development server with live reloading:

```bash
uvicorn api.main:app --reload
```

or

```bash
fastapi dev
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

- Manages async PostgreSQL connection pools using `asyncpg` for both write (primary) and read (replica) databases.
- Supports read-write splitting with per-region read pools, round-robin load balancing, health checks, and automatic failover.
- Provides convenient async helpers used throughout the codebase:
    - `DataBase.create_pool(write_uri, read_uris, ...)` — initialize pools
    - `DataBase.fetch(...)`, `DataBase.fetchrow(...)`, `DataBase.fetchval(...)`, `DataBase.write(...)`, `DataBase.execute(...)` — query helpers
    - `DataBase.get_pool_stats()` and `DataBase.health_check()` — runtime diagnostics
    - `DataBase.close_pool()` — graceful shutdown
- Exposes a FastAPI dependency `get_db()` (yields the `DataBase` class) for DI in route handlers and background tasks.

How to configure:

- The project uses `api/core/config.py` (Pydantic settings). Important settings for DB behavior are:
    - `PRIMARY_DATABASE_URL` — connection URL for the primary (write) DB
    - `REPLICA_DATABASE_URL` — a replica/read URL (used in the example initialization)
    - `HEALTH_CHECK_INTERVAL` — seconds between automatic health checks (0 to disable)
    - `REGION_PRIORITY` — list of region names to prefer when routing reads

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

- If you don't configure read replicas, the code will fall back to using the write pool for reads.
- The DB implementation uses a custom `CustomRecord` (wrapping `asyncpg.Record`) to make conversion to Pydantic models simple and fast.
- Health checks run in a background task (when `HEALTH_CHECK_INTERVAL > 0`) and update per-pool health/latency metrics that the routing logic uses to prefer healthy, low-latency pools.

## Caching (api/core/cache.py)

The project implements a flexible caching mechanism using Redis, designed to improve performance for read-heavy operations.

### Features

- **Decorators**:
    - `@cache`: Caches the result of a function. Supports both simple keys (Redis Strings) and Hash fields (Redis Hashes).
    - `@cache_invalidate`: Automatically invalidates cache keys (or Hash fields) after a function executes (useful for create/update/delete operations).
- **Serialization**: Automatically handles Pydantic models and lists of models using `model_validate` and `model_dump`.
- **Centralized Keys**: All Redis key patterns are defined in `api/shared/redis_keys.py` to prevent key collisions and ensure consistency.

### Usage Example

**1. Define Keys:**

```python
# api/shared/redis_keys.py
class RedisKeys:
    ROLES_CACHE = "roles_cache"  # Hash Key
    ROLE_FIELD_BY_ID = "{role_id}"  # Hash Field
```

**2. Cache a Method:**

```python
# api/apps/user/v0/dao/role.py
from api.core.cache import cache
from api.shared.redis_keys import RedisKeys

@cache(key_pattern=RedisKeys.ROLE_FIELD_BY_ID, hash_key=RedisKeys.ROLES_CACHE, model=RoleData)
async def get_role_by_id(self, role_id: UUID) -> Optional[RoleData]:
    # ... fetch from DB ...
```

**3. Invalidate on Update:**

```python
# api/apps/user/v0/dao/role.py
from api.core.cache import cache_invalidate

@cache_invalidate(key_pattern=RedisKeys.ROLE_FIELD_BY_ID, hash_key=RedisKeys.ROLES_CACHE)
async def update_role(self, role_id: UUID, role_update: RoleUpdate) -> RoleData:
    # ... update DB ...
```

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

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def list_all_users(self) -> List[dict[str, Any]]:
    """
    A Celery task that fetches a list of all users from the database.

    Returns:
        A list of user records as dictionaries.
    """
    # self.db and self.loop come from the AsyncBaseTask in celery_app.py
    user_dao = UserDAO(db=self.db)

    logger.info("Executing task: list_all_users")
    # Use the task's event loop to run the async DAO method.
    records = self.loop.run_until_complete(user_dao.get_all_users())
    logger.info("Fetched %d users from the database.", len(records))
    return [user.model_dump() for user in records]
```

## User Management & Authentication

The project comes with a comprehensive user management system located in `api/apps/user`.

### Features

- **Authentication**:
    - **JWT Auth**: Secure access and refresh token rotation.
    - **OAuth2**: Google Login integration.
- **Session Management**:
    - Track active sessions.
    - Revoke specific sessions (logout from specific devices).
- **Security**:
    - **Sudo Mode**: Require re-authentication (or "sudo token") for sensitive actions like changing passwords.
    - **Password Hashing**: Uses `bcrypt` for secure password storage.
- **Profile**:
    - Update user details.
    - Profile picture support (integrated with S3).

## AWS S3 Integration

The project includes a robust AWS S3 integration for handling file uploads and deletions, designed with security and performance in mind.

### Configuration

Ensure the following environment variables are set in your `.env` file:

- `AWS_ACCESS_KEY`: Your AWS access key ID.
- `AWS_SECRET_ACCESS_KEY`: Your AWS secret access key.
- `AWS_BUCKET_NAME`: The name of your S3 bucket.
- `S3_REGION_NAME`: The AWS region (e.g., `us-east-1`).
- `S3_ENDPOINT_URL`: The S3 endpoint URL (use `http://localhost:4566` for LocalStack).

### Features

1.  **Secure Direct Uploads (Presigned POST)**:
    - The backend generates a **Presigned POST URL** and a set of fields.
    - The frontend uses these to upload files directly to S3, bypassing the backend server for better performance.
    - **Security Policies**:
        - **Max File Size**: 5MB (enforced by S3).
        - **File Type**: Must be an image (`image/*`) (enforced by S3).
        - **Tagging**: Files are automatically tagged with `status=temporary`.

2.  **Authenticated Deletion**:
    - Deleting files requires authentication (`DELETE /api/v0/s3/file`).

3.  **Smart URL Generation**:
    - `GET /api/v0/s3/file/{key}` returns a URL that forces the browser to display the file inline (instead of downloading) by setting the correct `Content-Type` and `Content-Disposition`.

4.  **Automatic Cleanup**:
    - A Celery task (`api/tasks/delete_s3_files.py`) runs periodically to delete "temporary" files that haven't been saved (referenced by the backend) within 15 minutes.
    - **Flow**:
        1.  User uploads file -> Tagged `status=temporary`.
        2.  User saves profile -> Backend should update tag to `status=saved` (implementation dependent) or simply reference the key.
        3.  If not saved, the cleanup task deletes it after 15 mins.

### Usage Example

**1. Get Upload URL (Frontend):**

```http
POST /api/v0/s3/upload-url
Content-Type: application/json

{
  "filename": "avatar.png",
  "content_type": "image/png"
}
```

**Response:**

```json
{
    "upload_url": "https://s3.amazonaws.com/...",
    "fields": {
        "key": "uuid/avatar.png",
        "AWSAccessKeyId": "...",
        "policy": "...",
        "signature": "...",
        "Content-Type": "image/png",
        "x-amz-tagging": "status=temporary"
    },
    "key": "uuid/avatar.png",
    "expires_in": 3600
}
```

**2. Upload to S3 (Frontend):**

Use the `upload_url` and `fields` to make a `POST` request. The file must be the **last** field.

```javascript
const formData = new FormData();
Object.entries(response.fields).forEach(([key, value]) => {
    formData.append(key, value);
});
formData.append("file", fileObject);

await fetch(response.upload_url, {
    method: "POST",
    body: formData,
});
```

## Notification System

The project includes a robust, versioned Notification System designed for scalability and multi-channel support using the Strategy Pattern.

### Architecture

- **Service**: `NotificationService` (Singleton) dispatches messages to registered channels.
- **Channels**:
    - **Base**: `BaseNotificationChannel` (Abstract strategy).
    - **WebSockets**: Real-time notifications to connected clients. Supports personal messages and broadcasting.
    - **Future (SMS/Email)**: Easily extensible by inheriting from `BaseNotificationChannel`.
- **Structure**: Located in `api/apps/notification/v0`. Schemas are shared in `api/apps/notification/schemas.py`.

### WebSockets

- **Endpoint**: `/api/v0/notifications/ws`
- **Auth**: Query parameter `?token=<JWT_TOKEN>`.
- **Features**:
    - **Authentication**: Validates JWT and checks User status (must be active).
    - **Connections**: Supports multiple connections per user (e.g., Phone + Laptop).
    - **Broadcast**: `notification_service.broadcast_all("message")` sends to everyone.

### Extending (Adding Email/SMS)

To add a new channel (e.g., Email), simply create a new class inheriting from `BaseNotificationChannel`:

```python
# api/apps/notification/v0/channels/email.py
from api.apps.notification.v0.channels.base import BaseNotificationChannel
from api.apps.notification.schemas import NotificationSchema


class EmailChannel(BaseNotificationChannel):
    async def send(self, user_id: UUID, notification: NotificationSchema) -> None:
        # User internal UserDAO to get email, then send using SMTP/SES
        pass

    async def broadcast(self, notification: NotificationSchema) -> None:
        # Loop all users or use bulk API
        pass
```

Then register it in the service:

```python
# api/apps/notification/v0/service.py
notification_service.register_channel(EmailChannel())
```

### Usage

**1. Dependency Injection**

Use `get_notification_service` to inject the service into your routes.

```python
from fastapi import APIRouter, Depends
from api.apps.notification.v0.service import NotificationService, get_notification_service

router = APIRouter()


@router.post("/send")
async def send_notification(service: NotificationService = Depends(get_notification_service)):
    await service.notify(user_id=..., message="Hello!")
```

**2. Background Tasks (Celery)**

For better performance, run notifications in the background.

```python
from api.apps.notification.v0.tasks import send_notification_task

# Fire and forget
send_notification_task.delay(
    user_id_str="user-uuid-string", message="Your report is ready!", notification_type="success"
)
```

## Event Bus

The project features a decentralized, robust **Event Bus** architecture powered by Redis Pub/Sub. This enables loosely-coupled asynchronous communication between different backend domains. All local application instances share the unified event loop ensuring reliability and exactly-once processing via distributed locking.

### Architecture

- **Event Schema**: All events inherit from `ApplicationEvent` (in `api/core/events/schema.py`) enforcing a standard structure containing `event_name` and `payload`.
- **Broker**: Redis Pub/Sub broadcasts the events across all active API workers ensuring durability and scaling.
- **Locking**: The backend implements a Redis-based distributed lock (`SETNX` with TTL) prior to triggering subscribers. This secures exactly-once processing of events, preventing race conditions or duplicate notification dispatches if 5+ API workers consume the exact same Pub/Sub broadcast at the identical millisecond.

### Defining and Listening to Events

1. **Define an Event Name:**

```python
# api/core/events/constants.py
class EventNames:
    USER_CREATED = "user.created"
```

2. **Publish the Event:**

To dispatch an event payload from anywhere within the API (e.g., inside the User Service after login):

```python
from api.core.events.bus import event_bus
from api.core.events.schema import ApplicationEvent
from api.core.events.constants import EventNames

await event_bus.publish(
    ApplicationEvent(
        event_name=EventNames.USER_CREATED,
        payload={"user_id": str(user.id), "email": user.email, "username": user.username},
    )
)
```

3. **Subscribe to the Event:**

Listening for events across different app domains is simple and highly decoupled using our decorator factory (e.g., triggering a Welcome Email when the `user.created` event hits the system):

```python
# api/apps/notification/v0/listeners/user_created.py
from api.apps.notification.schemas import NotificationType
from api.apps.notification.v0.listeners.utils import register_notification_listener
from api.core.events.constants import EventNames

on_user_created = register_notification_listener(
    event_name=EventNames.USER_CREATED,
    notification_type=NotificationType.INFO,
    subject="Welcome to FastAPI Template!",
    message="Your registration was successful.",
    template_path="email/welcome.html",
)
```

## Feature Management (Flagsmith)

The project integrates [Flagsmith](https://flagsmith.com/) for feature flag management, allowing you to toggle features, manage rollouts, and target specific user segments without code deploys.

### Configuration

Add your server-side environment key to `.env`:

```bash
FLAGSMITH_ENVIRONMENT_KEY=<your_key>
```

### Usage

**1. Route Dependency**

Protect endpoints using the `feature_enabled` dependency. You can optionally pass `identity` and `traits` for targeted rollouts.

```python
from fastapi import Depends
from api.core.feature_flags import feature_enabled


@router.get("/beta-feature")
async def beta_endpoint(enabled: bool = Depends(feature_enabled("beta_feature"))):
    if not enabled:
        return {"message": "Feature disabled"}
    return {"message": "Welcome to Beta!"}
```

**2. Advanced Targeting (Identity & Traits)**

To target specific users or segments (e.g., "Beta Users"), pass the identity and traits:

```python
# Check if feature is enabled for user_123 with specific traits
Depends(feature_enabled("new_dashboard", identity="user_123", traits={"role": "beta"}))
```

## Monitoring

The project includes a comprehensive monitoring stack using **Prometheus** and **Grafana** to provide deep visibility into application performance, database health, and background task processing.

### Accessing the Dashboard

When running with Docker, the monitoring services are available at:

- **Grafana**: [http://localhost:3000](http://localhost:3000) (User: `admin`, Password: `admin`)
- **Prometheus**: [http://localhost:9090](http://localhost:9090)
- **Celery Flower**: [http://localhost:5555](http://localhost:5555)

A pre-configured **FastAPI Dashboard** is automatically provisioned. It provides real-time insights into:

1.  **Overview**: Top-level gauges for Total Requests, DB Queries, Failed Requests, and Cache status.
2.  **Application Health**: Request rates, error rates (5xx/4xx), and detailed latency percentiles (P50, P95, P99).
3.  **System Resources**: Container CPU and Memory usage.
4.  **Database Metrics**:
    - Connection pool usage (Read/Write pools).
    - Query throughput and latency histograms.
    - Cache hit ratios and active transaction counts.
5.  **Cache & Redis**: Redis operations throughput, cache hit/miss rates, and latency.
6.  **Celery Tasks**: Queue lengths and task states (Success/Failure/Retry).

### Key Metrics Instrumented

- **HTTP**: `http_requests_total`, `http_request_duration_seconds`, `http_request_size_bytes`
- **Database**: `db_query_total`, `db_query_duration_seconds`, `db_pool_connections_in_use`
- **Cache**: `cache_requests_total`, `cache_hit_miss_total`
- **Celery**: `celery_tasks_total`, `celery_queue_length`

---

## Code Quality

This project is configured with a suite of tools to ensure high code quality.

**Auto-format Code:**

```bash
uv run ruff format
```

**Run All Checks:**

```bash
# Run linter
uv run pylint .

# Run formatter and linter
uv run ruff check .

# Run static type checker
uv run mypy .
```
