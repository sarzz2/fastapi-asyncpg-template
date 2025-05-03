import datetime
import logging

from fastapi import HTTPException

from app.core.auth import get_password_hash, verify_password
from app.core.database import DataBase

log = logging.getLogger("fastapi")


async def get_user(username: str):
    query = """
           SELECT users.id, users.username, users.email, users.profile_picture_url
             FROM users
            WHERE users.id = $1;

       """
    return await DataBase.fetchrow(query, username)


async def get_user_password(user_id: str):
    query = """
           SELECT users.id, users.username, users.email, users.password
             FROM users
            WHERE id = $1;

       """
    return await DataBase.fetchrow(query, user_id)


async def search_user(term: str):
    query = """
            SELECT u.id, u.username, u.email, u.profile_picture_url
              FROM users u
             WHERE (u.username ILIKE '%' || $1 || '%'
                OR u.email ILIKE '%' || $1 || '%')
             LIMIT 15;
    """
    users = await DataBase.fetch(query, term)
    if users:
        return [dict(user) for user in users]
    return {"message": "No user found"}


async def register_user(user_id: str, username: str, email: str, password: str):
    query = """
               INSERT INTO users (id, username, email, password)
                    VALUES ($1, $2, $3, $4);
           """
    return await DataBase.execute(query, user_id, username, email, get_password_hash(password))


async def authenticate_user(username: str, password: str):
    query = """
               SELECT id, username, email, password
                 FROM users
                WHERE username = $1;
           """
    user = await DataBase.fetchrow(query, username)
    if user and verify_password(password, user.password):
        return user
    return None


async def update_user_password(password: str, user_id: str):
    query = """
               UPDATE users SET password = $1
                WHERE id = $2
               """
    return await DataBase.execute(query, get_password_hash(password), user_id)


async def get_sessions(user_id: str):
    query = """
        SELECT user_id, u.username, issued_at, expires_at, user_agent, jti
          FROM sessions s
         INNER JOIN users u ON u.id = s.user_id
         WHERE user_id = $1;
    """
    return await DataBase.fetch(query, user_id)


async def revoke_user_session(current_user, jti: str, redis) -> None:
    query = """
        SELECT extract(epoch FROM expires_at) - extract(epoch FROM now()) AS ttl
         FROM sessions WHERE jti = $1 AND user_id = $2;
    """
    row = await DataBase.fetchrow(
        query,
        jti,
        current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Session not found")

    await DataBase.execute(
        "DELETE FROM sessions WHERE jti = $1 AND user_id = $2",
        jti,
        current_user["id"],
    )
    ttl = max(int(row["ttl"]), 0)
    # blacklist both access and refresh JTIs
    await redis.set(f"blacklist:access:{jti}", 1, ex=ttl)
    await redis.set(f"blacklist:refresh:{jti}", 1, ex=ttl)


async def create_user_session(user_id: str, jti: str, expires_delta: datetime.timedelta, ip: str, user_agent: str):
    query = """
       INSERT INTO sessions (jti, user_id, issued_at, expires_at, ip_address, user_agent)
            VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (user_id, user_agent) DO UPDATE
               SET jti = $1, user_id = $2, issued_at = $3, expires_at = $4, ip_address = $5;
    """
    return await DataBase.execute(
        query,
        jti,
        user_id,
        datetime.datetime.now(datetime.UTC),
        datetime.datetime.now(datetime.UTC) + expires_delta,
        ip,
        user_agent,
    )


async def update_user(user_id: str, **kwargs):
    """
    Update the users table and upsert additional_user_details in a single query.
    This uses parameterized SQL to avoid injection and uses COALESCE to preserve
    existing values if a new value is null.
    """
    query = """
               WITH updated_user AS (
             UPDATE users
                SET username = COALESCE($2, username), email = COALESCE($3, email),
                    profile_picture_url = COALESCE($4, profile_picture_url)
              WHERE id = $1
          RETURNING id, username, email, profile_picture_url
               )
             SELECT * FROM updated_user;
       """
    # Prepare parameter values in order.
    params = [
        user_id,
        kwargs.get("username"),
        kwargs.get("email"),
        kwargs.get("profile_picture_url"),
    ]
    return await DataBase.fetchrow(query, *params)
