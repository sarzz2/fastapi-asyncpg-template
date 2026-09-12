import logging

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response
from starlette_admin import BaseAdmin
from starlette_admin.auth import AdminUser, AuthProvider
from starlette_admin.exceptions import LoginFailed
from starlette_admin.i18n import I18nConfig, TimezoneConfig

from api.apps.common.admin_views.dashboard import DashboardView
from api.apps.common.admin_views.dead_letter_task import DeadLetterTaskAdminView
from api.apps.common.admin_views.periodic_task import PeriodicTaskAdminView
from api.apps.user.admin_views.role import RoleAdminView
from api.apps.user.admin_views.user import UserAdminView
from api.apps.user.admin_views.version import AppVersionAdminView
from api.apps.user.v0.dao.user import UserDAO
from api.constants import AdminConstants
from api.core.auth import verify_password
from api.core.config import settings
from api.core.database import DataBase

logger = logging.getLogger("fastapi")


class AdminAuthProvider(AuthProvider):
    """Custom AuthProvider for Starlette-Admin requiring super admin credentials."""

    def __init__(
        self,
        user_dao: UserDAO | None = None,
        db: DataBase | None = None,
        login_path: str = "/login",
        logout_path: str = "/logout",
    ) -> None:
        """
        Initialize AdminAuthProvider with injected UserDAO dependency.

        Args:
            user_dao (UserDAO | None): Data Access Object for user operations. Defaults to None.
            db (DataBase | None): Database connection instance. Defaults to None.
            login_path (str): Login route path. Defaults to "/login".
            logout_path (str): Logout route path. Defaults to "/logout".
        """
        super().__init__(login_path=login_path, logout_path=logout_path)
        self.db = db or DataBase()
        self.user_dao = user_dao or UserDAO(self.db)

    async def login(
        self,
        username: str,
        password: str,
        remember_me: bool,
        request: Request,
    ) -> Response | None:
        """
        Authenticate user against database and verify super admin role.

        Args:
            username (str): Entered username or email.
            password (str): Entered plain text password.
            remember_me (bool): Remember session flag.
            request (Request): The incoming Starlette/FastAPI request.

        Returns:
            Response | None: Response object or None on default redirect.

        Raises:
            LoginFailed: If authentication or role verification fails.
        """
        user = await self.user_dao.get_by_email(username)
        if not user:
            user = await self.user_dao.get_by_username(username)

        if not user or not user.hashed_password:
            raise LoginFailed("Invalid username/email or password")

        if not verify_password(password, user.hashed_password):
            raise LoginFailed("Invalid username/email or password")

        if not user.is_active:
            raise LoginFailed("User account is inactive")

        # Verify Super Admin role assignment
        has_super_admin_role = any(role.name == "Super Admin" for role in user.roles)
        if not has_super_admin_role:
            raise LoginFailed("Access denied: Super Admin role required")

        request.session["admin_user"] = {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
        }
        return None

    async def logout(self, request: Request) -> Response | None:
        """
        Clear user session on logout.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.

        Returns:
            Response | None: Response object or None on default redirect.
        """
        request.session.clear()
        return None

    async def authenticate(self, request: Request) -> AdminUser | None:
        """
        Check active admin session.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.

        Returns:
            AdminUser | None: AdminUser instance if session is valid, None otherwise.
        """
        admin_data = request.session.get("admin_user")
        if admin_data and isinstance(admin_data, dict):
            name = admin_data.get("full_name") or admin_data.get("username") or admin_data.get("email") or "Admin"
            return AdminUser(username=str(name))
        return None


def setup_admin(app: FastAPI) -> BaseAdmin:
    """
    Initialize Starlette-Admin portal, attach auth provider, register views, and mount to FastAPI app.

    Args:
        app (FastAPI): The FastAPI application instance.

    Returns:
        BaseAdmin: Configured Starlette-Admin instance.
    """
    db = DataBase()
    user_dao = UserDAO(db)

    i18n_config = I18nConfig(
        default_locale="en",
        language_switcher=AdminConstants.SUPPORTED_LANGUAGES,
    )
    timezone_config = TimezoneConfig(
        default_timezone="UTC",
        timezone_switcher=AdminConstants.SUPPORTED_TIMEZONES,
    )

    admin = BaseAdmin(
        title=f"{settings.PROJECT_NAME} Admin",
        auth_provider=AdminAuthProvider(user_dao=user_dao),
        secret_key=settings.SECRET_KEY,
        static_dir="api/static",
        index_view=DashboardView(db=db),
        i18n_config=i18n_config,
        timezone_config=timezone_config,
    )
    admin.add_view(UserAdminView(db=db))
    admin.add_view(RoleAdminView(db=db))
    admin.add_view(AppVersionAdminView(db=db))
    admin.add_view(PeriodicTaskAdminView(db=db))
    admin.add_view(DeadLetterTaskAdminView(db=db))
    admin.mount_to(app)

    logger.info("Starlette-Admin portal mounted successfully at /admin")
    return admin
