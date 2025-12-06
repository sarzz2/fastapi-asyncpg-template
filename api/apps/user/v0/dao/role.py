# pylint: disable=duplicate-code
import asyncio
from typing import List, Optional
from uuid import UUID

from fastapi import Depends

from api.apps.user.schemas.role import PermissionData, RoleCreate, RoleData, RoleUpdate
from api.core.cache import cache, cache_invalidate
from api.core.database import DataBase, get_db
from api.shared.redis_keys import RedisKeys


class RoleDAO:
    """Data Access Object for role-related database operations."""

    def __init__(self, db: DataBase):
        """Initialize the RoleDAO with a database connection."""
        self.db = db

    @cache(key_pattern=RedisKeys.ROLE_FIELD_ALL, hash_key=RedisKeys.ROLES_CACHE, model=RoleData)
    async def get_all_roles(self) -> List[RoleData]:
        """
        Retrieve all roles with their permissions.
        Returns:
            List[RoleData]: List of roles.
        """
        query = """
            SELECT
                r.id,
                r.name,
                r.description,
                r.created_at,
                r.updated_at,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'id', p.id,
                            'name', p.name,
                            'description', p.description,
                            'created_at', p.created_at
                        )
                    ) FILTER (WHERE p.id IS NOT NULL), '[]'
                ) as permissions
            FROM roles r
            LEFT JOIN role_permissions rp ON r.id = rp.role_id
            LEFT JOIN permissions p ON rp.permission_id = p.id
            GROUP BY r.id
        """
        records = await self.db.fetch(query, fetch_row=False)
        if records is None:
            records = []
        return [RoleData.model_validate(dict(record)) for record in records]

    async def _get_role_by_id(self, role_id: UUID) -> Optional[RoleData]:
        """
        Get a role by ID (Internal, no cache).
        """
        query = """
            SELECT
                r.*,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'id', p.id,
                            'name', p.name,
                            'description', p.description,
                            'created_at', p.created_at
                        )
                    ) FILTER (WHERE p.id IS NOT NULL), '[]'
                ) as permissions
            FROM roles r
            LEFT JOIN role_permissions rp ON r.id = rp.role_id
            LEFT JOIN permissions p ON rp.permission_id = p.id
            WHERE r.id = $1
            GROUP BY r.id
        """
        record = await self.db.fetch(query, role_id, model=RoleData, fetch_row=True)
        return record

    @cache(key_pattern=RedisKeys.ROLE_FIELD_BY_ID, hash_key=RedisKeys.ROLES_CACHE, model=RoleData)
    async def get_role_by_id(self, role_id: UUID) -> Optional[RoleData]:
        """
        Get a role by ID.
        Args:
            role_id: Role ID.
        Returns:
            Optional[RoleData]: Role data.
        """
        return await self._get_role_by_id(role_id)

    async def get_role_by_name(self, name: str) -> Optional[RoleData]:
        """
        Get a role by name.
        Args:
            name: Role name.
        Returns:
            Optional[RoleData]: Role data.
        """
        query = """
            SELECT
                r.*,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'id', p.id,
                            'name', p.name,
                            'description', p.description,
                            'created_at', p.created_at
                        )
                    ) FILTER (WHERE p.id IS NOT NULL), '[]'
                ) as permissions
            FROM roles r
            LEFT JOIN role_permissions rp ON r.id = rp.role_id
            LEFT JOIN permissions p ON rp.permission_id = p.id
            WHERE r.name = $1
            GROUP BY r.id
        """
        record = await self.db.fetch(query, name, model=RoleData, fetch_row=True)
        return record

    @cache_invalidate(key_pattern=RedisKeys.ROLE_FIELD_ALL, hash_key=RedisKeys.ROLES_CACHE)
    async def create_role(self, role_create: RoleCreate) -> RoleData:
        """
        Create a new role.
        Args:
            role_create: Role creation data.
        Returns:
            RoleData: Created role data.
        """
        # 1. Create Role
        query_role = """
            INSERT INTO roles (name, description)
            VALUES ($1, $2)
            RETURNING *
        """
        role_record = await self.db.write(query_role, role_create.name, role_create.description, model=RoleData)
        role_id = role_record.id

        # 2. Assign Permissions
        if role_create.permission_ids:
            values = [(role_id, pid) for pid in role_create.permission_ids]
            await self.db.execute(
                "INSERT INTO role_permissions (role_id, permission_id) SELECT * FROM UNNEST($1::uuid[], $2::uuid[])",
                [v[0] for v in values],
                [v[1] for v in values],
            )

        # Return created role with permissions
        # We need to fetch it again to get the permissions structure
        # We know it exists, so we can cast or assert
        role = await self._get_role_by_id(role_id)
        if not role:
            raise ValueError("Failed to fetch created role")
        return role

    @cache_invalidate(
        key_pattern=[RedisKeys.ROLE_FIELD_ALL, RedisKeys.ROLE_FIELD_BY_ID], hash_key=RedisKeys.ROLES_CACHE
    )
    async def update_role(self, role_id: UUID, role_update: RoleUpdate) -> Optional[RoleData]:
        """
        Update a role.
        Args:
            role_id: Role ID.
            role_update: Role update data.
        Returns:
            Optional[RoleData]: Updated role data.
        """
        # 1. Update Role fields
        if role_update.name is not None or role_update.description is not None:
            query_update = """
                UPDATE roles
                SET
                    name = COALESCE($1, name),
                    description = COALESCE($2, description),
                    updated_at = NOW()
                WHERE id = $3
                RETURNING *
            """
            await self.db.write(query_update, role_update.name, role_update.description, role_id, model=RoleData)

        # 2. Update Permissions if provided
        if role_update.permission_ids is not None:
            # Delete existing
            await self.db.execute("DELETE FROM role_permissions WHERE role_id = $1", role_id)
            # Insert new
            if role_update.permission_ids:
                values = [(role_id, pid) for pid in role_update.permission_ids]
                await self.db.execute(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT * FROM UNNEST($1::uuid[], $2::uuid[])",
                    [v[0] for v in values],
                    [v[1] for v in values],
                )

        # 3. Invalidate tokens for users with this role
        # We increment token_version for all users who have this role assigned
        await self.db.execute(
            """
            UPDATE users u
            SET token_version = u.token_version + 1
            FROM user_roles ur
            WHERE u.id = ur.user_id AND ur.role_id = $1
            """,
            role_id,
        )

        # Return updated role with permissions
        return await self._get_role_by_id(role_id)

    @cache_invalidate(
        key_pattern=[RedisKeys.ROLE_FIELD_ALL, RedisKeys.ROLE_FIELD_BY_ID], hash_key=RedisKeys.ROLES_CACHE
    )
    async def delete_role(self, role_id: UUID) -> None:
        """
        Delete a role and its associated permissions.
        Args:
            role_id: Role ID.
        """
        # Delete associated permissions and the role concurrently
        await asyncio.gather(
            self.db.execute("DELETE FROM role_permissions WHERE role_id = $1", role_id),
            self.db.execute("DELETE FROM roles WHERE id = $1", role_id),
            self.db.execute("UPDATE users SET token_version = token_version + 1 WHERE id = $1", role_id),
        )

    async def get_all_permissions(self) -> List[PermissionData]:
        """
        Retrieve all permissions.
        Returns:
            List[PermissionData]: List of permissions.
        """
        query = "SELECT * FROM permissions"
        return await self.db.fetch(query, model=PermissionData, fetch_row=False)


async def get_role_dao(db: DataBase = Depends(get_db)) -> RoleDAO:
    """Dependency to get RoleDAO."""
    return RoleDAO(db=db)
