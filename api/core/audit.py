"""
Audit logging service for operational and asynchronous audit event dispatching.
"""

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from starlette.background import BackgroundTasks
from starlette.requests import Request

from api.core.context import CLIENT_IP, CURRENT_ACTOR_ID, CURRENT_IMPERSONATOR_ID
from api.core.database import DataBase
from api.utils.serialization import json_serialize_safe

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Unified service to log audit events asynchronously across API routes, admin views, and background tasks.
    """

    @staticmethod
    async def _save_audit_log(
        actor_id: str,
        action: str,
        resource: str,
        resource_id: str,
        details: dict[str, Any],
        ip_address: str | None,
        impersonator_id: str | None = None,
    ) -> None:
        """
        Execute raw SQL insert into the audit_logs table.

        Args:
            actor_id: The ID of the actor who performed the action.
            action: The action performed (e.g., 'DLQ_TASK_TRIGGER').
            resource: The resource type (e.g., 'dlq_task').
            resource_id: The ID of the specific resource.
            details: A dictionary containing event details.
            ip_address: The IP address of the actor.
            impersonator_id: The ID of the administrator impersonating the actor (if any).
        """
        query = """
            INSERT INTO audit_logs (actor_id, impersonator_id, action, resource, resource_id, details, ip_address)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb, $7)
        """
        try:
            await DataBase.execute(
                query,
                actor_id,
                impersonator_id,
                action,
                resource,
                str(resource_id),
                json.dumps(json_serialize_safe(details)),
                ip_address,
            )
            logger.debug(
                "Audit log saved successfully: action=%s resource=%s resource_id=%s actor_id=%s",
                action,
                resource,
                resource_id,
                actor_id,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Failed to save audit log for action=%s, resource=%s: %s", action, resource, e)

    @classmethod
    def log(  # pylint: disable=too-many-locals
        cls,
        action: str,
        resource: str,
        resource_id: str | UUID,
        details: dict[str, Any] | None = None,
        *,
        actor_id: str | UUID | None = None,
        impersonator_id: str | UUID | None = None,
        request: Request | None = None,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        """
        Record an operational audit log asynchronously.

        Handles API routes, Starlette-Admin views, and background jobs uniformly:
        - Resolves `actor_id` from parameter, `CURRENT_ACTOR_ID` contextvar,
          or `request.session['admin_user']['id']`.
        - Resolves `ip_address` from `CLIENT_IP` contextvar or request headers.
        - Dispatches via `background_tasks.add_task` if provided (FastAPI routes),
          or `asyncio.create_task` if omitted (Admin views / background services).

        Args:
            action: The action performed (e.g. AuditActions.DLQ_TASK_TRIGGER).
            resource: The resource type (e.g. AuditResources.DLQ_TASK).
            resource_id: The ID of the specific resource.
            details: Optional dictionary containing event details.
            actor_id: Optional ID of authenticated user (defaults to context user).
            request: Optional Request object for fallback context.
            background_tasks: Optional FastAPI BackgroundTasks instance.
        """
        resolved_actor_id = actor_id or CURRENT_ACTOR_ID.get()
        resolved_impersonator_id = impersonator_id or CURRENT_IMPERSONATOR_ID.get()
        if not resolved_actor_id and request:
            admin_user = request.session.get("admin_user") or {}
            resolved_actor_id = admin_user.get("id")

        if not resolved_actor_id:
            logger.warning(
                "Skipping audit log for action=%s, resource=%s: actor_id could not be resolved",
                action,
                resource,
            )
            return

        if details is None:
            details_payload: dict[str, Any] = {}
        elif isinstance(details, dict):
            details_payload = details
        else:
            logger.warning(
                "Audit log details for action=%s is not a dictionary (%s); wrapping in payload",
                action,
                type(details),
            )
            details_payload = {"value": details}

        # Resolve IP address from context or request headers
        ip_address = CLIENT_IP.get()
        if not ip_address and request:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                ip_address = forwarded.split(",")[0].strip()
            elif request.client:
                ip_address = request.client.host

        logger.debug(
            "Scheduling audit log: action=%s resource=%s resource_id=%s actor_id=%s",
            action,
            resource,
            resource_id,
            resolved_actor_id,
        )

        if background_tasks is not None:
            background_tasks.add_task(
                cls._save_audit_log,
                actor_id=str(resolved_actor_id),
                action=action,
                resource=resource,
                resource_id=str(resource_id),
                details=details_payload,
                ip_address=ip_address,
                impersonator_id=str(resolved_impersonator_id) if resolved_impersonator_id else None,
            )
        else:
            task_coro = cls._save_audit_log(
                actor_id=str(resolved_actor_id),
                action=action,
                resource=resource,
                resource_id=str(resource_id),
                details=details_payload,
                ip_address=ip_address,
                impersonator_id=str(resolved_impersonator_id) if resolved_impersonator_id else None,
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(task_coro)
            except RuntimeError:
                asyncio.run(task_coro)

    @classmethod
    async def log_admin(
        cls,
        request: Request,
        action: str,
        resource: str,
        resource_id: str | UUID,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Deprecated alias for backward compatibility. Delegates to AuditLogger.log().
        """
        cls.log(
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details,
            request=request,
        )
