from api.apps.common.v0.dao.dead_letter_task import DeadLetterTaskDAO
from api.apps.notification.v0.service import NotificationService
from api.core.database import DataBase
from api.core.redis import RedisClient


class TaskContainer:
    """
    Dependency Injection Container for Celery tasks.
    Initializes required DAOs and Services once per worker process.
    """

    def __init__(self, db: DataBase, redis: RedisClient) -> None:
        self.db = db
        self.redis = redis

        # Initialize DAOs
        self.dead_letter_task_dao = DeadLetterTaskDAO(db=self.db)

        # Initialize Services
        self.notification_service = NotificationService()
