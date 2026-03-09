import asyncio
import os
import sys
import traceback

from api.apps.user.v0.dao.role import RoleDAO
from api.apps.user.v0.dao.user import UserDAO
from api.apps.user.v0.schemas.role import RoleCreate, RoleUpdate
from api.apps.user.v0.schemas.user import UserCreate
from api.core.auth import get_password_hash
from api.core.config import settings
from api.core.database import DataBase

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> None:
    """
    Create default admin user and assign super admin role to it.
    """
    print("Initializing database connection...")
    await DataBase.create_pool(write_uri=settings.PRIMARY_DATABASE_URL)
    db = DataBase()

    try:
        role_dao = RoleDAO(db)
        user_dao = UserDAO(db)

        # 1. Get all permissions
        print("Fetching all permissions...")
        permissions = await role_dao.get_all_permissions()
        permission_ids = [p.id for p in permissions]
        print(f"Found {len(permissions)} permissions.")

        # 2. Create or Update Super Admin Role
        role_name = "Super Admin"

        print(f"Checking for role '{role_name}'...")
        existing_role = await role_dao.get_role_by_name(role_name)

        if existing_role:
            print(f"Role '{role_name}' exists. Updating permissions...")

            await role_dao.update_role(existing_role.id, RoleUpdate(permission_ids=permission_ids))
            role_id = existing_role.id
        else:
            print(f"Creating role '{role_name}'...")
            new_role = await role_dao.create_role(
                RoleCreate(
                    name=role_name, description="Administrator with all permissions", permission_ids=permission_ids
                )
            )
            role_id = new_role.id

        print(f"Role '{role_name}' (ID: {role_id}) ready with {len(permission_ids)} permissions.")

        # 3. Create Default Admin User
        admin_email = "admin@example.com"
        admin_password = "AdminPassword123!"  # nosec

        print(f"Checking for user '{admin_email}'...")
        existing_user = await user_dao.get_by_email(admin_email)

        if existing_user:
            print(f"User '{admin_email}' exists.")
            user_id = existing_user.id
        else:
            print(f"Creating user '{admin_email}'...")
            new_user = await user_dao.create_user(
                UserCreate(
                    email=admin_email, username="admin", password=admin_password, full_name="System Administrator"
                ),
                hashed_password=get_password_hash(admin_password),
            )
            user_id = new_user.id
            print(f"User '{admin_email}' created (ID: {user_id}).")

        # 4. Assign Role to User
        print(f"Assigning role '{role_name}' to user '{admin_email}'...")
        await user_dao.assign_roles(user_id, [role_id])
        print("Role assigned successfully.")

    except Exception as e:  # pylint: disable=broad-except
        print(f"Error: {e}")

        traceback.print_exc()
    finally:
        await DataBase.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
