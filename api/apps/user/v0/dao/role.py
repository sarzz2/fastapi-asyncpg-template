from typing import Any
from uuid import UUID

from fastapi import Depends

from api.apps.user.v0.schemas.role import PermissionData, RoleCreate, RoleData, RoleUpdate
from api.core.cache import cache, cache_invalidate
from api.core.database import DataBase, get_db
from api.shared.redis_keys import RedisKeys


class RoleDAO:
    """Data Access Object for role-related database operations."""

    def __init__(self, db: DataBase):
        """Initialize the RoleDAO with a database connection."""
        self.db = db

    @cache(key_pattern=RedisKeys.ROLE_FIELD_ALL, hash_key=RedisKeys.ROLES_CACHE, model=RoleData)
    async def get_all_roles(self, limit: int = 20, cursor: UUID | None = None) -> list[RoleData]:
        """
        Retrieve all roles with their permissions.
        Args:
            limit: Limit the number of roles.
            cursor: Cursor for pagination (Role ID).
        Returns:
            List[RoleData]: List of roles.
        """
        if cursor:
            query = (
                "SELECT r.id, r.name, r.description, r.created_at, r.updated_at, "
                "COALESCE(json_agg(json_build_object("
                "'id', p.id, 'name', p.name, 'description', p.description, 'created_at', p.created_at"
                ")) FILTER (WHERE p.id IS NOT NULL), '[]') as permissions "
                "FROM roles r LEFT JOIN role_permissions rp ON r.id = rp.role_id "
                "LEFT JOIN permissions p ON rp.permission_id = p.id "
                "WHERE r.id < $1 GROUP BY r.id ORDER BY r.id DESC LIMIT $2;"
            )
            records = await self.db.fetch(query, cursor, limit, fetch_row=False)
        else:
            query = (
                "SELECT r.id, r.name, r.description, r.created_at, r.updated_at, "
                "COALESCE(json_agg(json_build_object("
                "'id', p.id, 'name', p.name, 'description', p.description, 'created_at', p.created_at"
                ")) FILTER (WHERE p.id IS NOT NULL), '[]') as permissions "
                "FROM roles r LEFT JOIN role_permissions rp ON r.id = rp.role_id "
                "LEFT JOIN permissions p ON rp.permission_id = p.id "
                "GROUP BY r.id ORDER BY r.id DESC LIMIT $1;"
            )
            records = await self.db.fetch(query, limit, fetch_row=False)

        if records is None:
            records = []
        return [RoleData.model_validate(dict(record)) for record in records]

    async def get_roles_paginated(
        self,
        limit: int = 100,
        skip: int = 0,
        search: str | None = None,
    ) -> list[RoleData]:
        """
        Retrieve paginated list of roles with permissions, with offset pagination.

        Args:
            limit (int): Maximum records to fetch. Defaults to 100.
            skip (int): Offset records count. Defaults to 0.
            search (str | None): Optional search query matching role name or description.

        Returns:
            list[RoleData]: List of matching role data models.
        """
        if search and search.strip():
            query = (
                "SELECT r.id, r.name, r.description, r.created_at, r.updated_at, "
                "COALESCE(json_agg(json_build_object("
                "'id', p.id, 'name', p.name, 'description', p.description, 'created_at', p.created_at"
                ")) FILTER (WHERE p.id IS NOT NULL), '[]') as permissions "
                "FROM roles r LEFT JOIN role_permissions rp ON r.id = rp.role_id "
                "LEFT JOIN permissions p ON rp.permission_id = p.id "
                "WHERE (r.name ILIKE $1 OR r.description ILIKE $1) "
                "GROUP BY r.id ORDER BY r.created_at DESC LIMIT $2 OFFSET $3;"
            )
            records = await self.db.fetch(query, f"%{search.strip()}%", limit, skip, fetch_row=False)
        else:
            query = (
                "SELECT r.id, r.name, r.description, r.created_at, r.updated_at, "
                "COALESCE(json_agg(json_build_object("
                "'id', p.id, 'name', p.name, 'description', p.description, 'created_at', p.created_at"
                ")) FILTER (WHERE p.id IS NOT NULL), '[]') as permissions "
                "FROM roles r LEFT JOIN role_permissions rp ON r.id = rp.role_id "
                "LEFT JOIN permissions p ON rp.permission_id = p.id "
                "GROUP BY r.id ORDER BY r.created_at DESC LIMIT $1 OFFSET $2;"
            )
            records = await self.db.fetch(query, limit, skip, fetch_row=False)
        if not records:
            return []
        return [RoleData.model_validate(dict(r)) for r in records]

    async def count_roles(self, search: str | None = None) -> int:
        """
        Count total number of role records, optionally matching search query.

        Args:
            search (str | None): Optional search query matching role name or description.

        Returns:
            int: Total count of matching roles.
        """
        if search and search.strip():
            query = "SELECT COUNT(*) as cnt FROM roles WHERE (name ILIKE $1 OR description ILIKE $1);"
            record = await self.db.fetch(query, f"%{search.strip()}%", fetch_row=True)
        else:
            record = await self.db.fetch("SELECT COUNT(*) as cnt FROM roles;", fetch_row=True)
        return int(record["cnt"]) if record else 0

    @cache_invalidate(hash_key=RedisKeys.ROLES_CACHE, invalidate_hash=True)
    async def delete_roles(self, role_ids: list[UUID]) -> int:
        """
        Delete multiple roles by primary key in bulk and invalidate Redis cache.

        Args:
            role_ids (list[UUID]): List of role UUIDs to delete.

        Returns:
            int: Number of deleted role records.
        """
        if not role_ids:
            return 0
        query = "DELETE FROM roles WHERE id = ANY($1::uuid[]) RETURNING id;"
        rows = await self.db.fetch(query, role_ids, fetch_row=False)
        return len(rows) if rows else 0

    async def _get_role_by_id(self, role_id: UUID) -> RoleData | None:
        """
        Get a role by ID (Internal, no cache).
        """
        query = (
            "SELECT r.id, r.name, r.description, r.created_at, r.updated_at, "
            "COALESCE(json_agg(json_build_object("
            "'id', p.id, 'name', p.name, 'description', p.description, 'created_at', p.created_at"
            ")) FILTER (WHERE p.id IS NOT NULL), '[]') as permissions "
            "FROM roles r LEFT JOIN role_permissions rp ON r.id = rp.role_id "
            "LEFT JOIN permissions p ON rp.permission_id = p.id "
            "WHERE r.id = $1 GROUP BY r.id;"
        )
        record = await self.db.fetch(query, role_id, model=RoleData, fetch_row=True)
        return record

    @cache(key_pattern=RedisKeys.ROLE_FIELD_BY_ID, hash_key=RedisKeys.ROLES_CACHE, model=RoleData)
    async def get_role_by_id(self, role_id: UUID) -> RoleData | None:
        """
        Get a role by ID.
        Args:
            role_id: Role ID.
        Returns:
            RoleData | None: Role data.
        """
        return await self._get_role_by_id(role_id)

    async def get_by_ids(self, pks: list[UUID]) -> list[RoleData]:
        """
        Retrieve multiple roles by primary key list.

        Args:
            pks (list[UUID]): List of role UUID primary keys.

        Returns:
            list[RoleData]: List of matching role objects.
        """
        if not pks:
            return []
        query = (
            "SELECT r.id, r.name, r.description, r.created_at, r.updated_at, "
            "COALESCE(json_agg(json_build_object("
            "'id', p.id, 'name', p.name, 'description', p.description, 'created_at', p.created_at"
            ")) FILTER (WHERE p.id IS NOT NULL), '[]') as permissions "
            "FROM roles r LEFT JOIN role_permissions rp ON r.id = rp.role_id "
            "LEFT JOIN permissions p ON rp.permission_id = p.id "
            "WHERE r.id = ANY($1::uuid[]) GROUP BY r.id ORDER BY r.created_at DESC;"
        )
        records = await self.db.fetch(query, pks, fetch_row=False)
        if not records:
            return []
        return [RoleData.model_validate(dict(r)) for r in records]

    async def get_role_by_name(self, name: str) -> RoleData | None:
        """
        Get a role by name.
        Args:
            name: Role name.
        Returns:
            RoleData | None: Role data.
        """
        query = (
            "SELECT r.id, r.name, r.description, r.created_at, r.updated_at, "
            "COALESCE(json_agg(json_build_object("
            "'id', p.id, 'name', p.name, 'description', p.description, 'created_at', p.created_at"
            ")) FILTER (WHERE p.id IS NOT NULL), '[]') as permissions "
            "FROM roles r LEFT JOIN role_permissions rp ON r.id = rp.role_id "
            "LEFT JOIN permissions p ON rp.permission_id = p.id "
            "WHERE r.name = $1 GROUP BY r.id;"
        )
        record = await self.db.fetch(query, name, model=RoleData, fetch_row=True)
        return record

    @cache_invalidate(hash_key=RedisKeys.ROLES_CACHE, invalidate_hash=True)
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

    @cache_invalidate(hash_key=RedisKeys.ROLES_CACHE, invalidate_hash=True)
    async def update_role(self, role_id: UUID, role_update: RoleUpdate) -> RoleData | None:
        """
        Update a role.
        Args:
            role_id: Role ID.
            role_update: Role update data.
        Returns:
            RoleData | None: Updated role data.
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

    @cache_invalidate(hash_key=RedisKeys.ROLES_CACHE, invalidate_hash=True)
    async def delete_role(self, role_id: UUID) -> None:
        """
        Delete a role and its associated permissions.
        Args:
            role_id: Role ID.
        """
        async with self.db.transaction() as conn:
            await conn.execute(
                "UPDATE users SET token_version = token_version + 1 "
                "WHERE id IN (SELECT user_id FROM user_roles WHERE role_id = $1)",
                role_id,
            )
            await conn.execute("DELETE FROM roles WHERE id = $1", role_id)

    async def get_all_permissions(self, limit: int = 20, cursor: UUID | None = None) -> list[PermissionData]:
        """
        Retrieve all permissions.
        Args:
            limit: Limit the number of permissions.
            cursor: Cursor for pagination (Permission ID).
        Returns:
            List[PermissionData]: List of permissions.
        """
        args: list[Any] = []
        if cursor:
            query = "SELECT * FROM permissions WHERE id < $1 ORDER BY id DESC LIMIT $2"
            args.append(cursor)
            args.append(limit)
        else:
            query = "SELECT * FROM permissions ORDER BY id DESC LIMIT $1"
            args.append(limit)

        return await self.db.fetch(query, *args, model=PermissionData, fetch_row=False)


async def get_role_dao(db: DataBase = Depends(get_db)) -> RoleDAO:
    """Dependency to get RoleDAO."""
    return RoleDAO(db=db)
