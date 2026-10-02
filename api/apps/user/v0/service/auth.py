import asyncio
import json
import logging
import re
import secrets
import string
import time
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from api.apps.user.v0.dao.role import RoleDAO, get_role_dao
from api.apps.user.v0.dao.user import UserDAO, get_user_dao
from api.apps.user.v0.schemas.auth import (
    ImpersonationResponse,
    ImpersonatorInfo,
    LoginResponse,
    SudoTokenResponse,
    Token,
    TokenData,
    TwoFactorChallengeResponse,
    TwoFactorConfirmResponse,
    TwoFactorSetupResponse,
    TwoFactorStatusResponse,
)
from api.apps.user.v0.schemas.role import RoleData
from api.apps.user.v0.schemas.user import UserCreate, UserData, UserSessionCreate
from api.constants import AuditActions, AuditResources, TokenTypes
from api.core.audit import AuditLogger
from api.core.auth import (
    create_access_token,
    create_impersonation_token,
    create_refresh_token,
    create_sudo_token,
    get_password_hash,
    verify_password,
    verify_token,
)
from api.core.config import settings
from api.core.context import CURRENT_IMPERSONATOR_ID
from api.core.events import ApplicationEvent, EventNames, event_bus
from api.core.i18n import trans
from api.core.redis import get_redis
from api.shared.redis_keys import RedisKeys
from api.utils.date import get_utc_now
from api.utils.totp import (
    decrypt_secret,
    encrypt_secret,
    generate_backup_codes,
    generate_provisioning_uri,
    generate_qr_code_svg,
    generate_totp_secret,
    verify_and_consume_backup_code,
    verify_totp,
)

logger = logging.getLogger("fastapi")


class AuthService:
    """Service layer for authentication operations.

    This class handles login, OAuth, token refresh, session management, and two-factor authentication.
    """

    def __init__(self, user_dao: UserDAO, role_dao: RoleDAO, redis: Redis):
        self._user_dao = user_dao
        self._role_dao = role_dao
        self._redis = redis

    async def _generate_unique_username(self, base_name: str) -> str:
        """
        Generate a unique username from a base name.
        """
        # Simple slugify: lowercase, remove non-alphanumeric, replace spaces with -
        username = re.sub(r"[^a-z0-9]+", "-", base_name.lower()).strip("-")
        if not username:
            username = "user"

        # Check if exists
        if not await self._user_dao.get_by_username(username):
            return username

        # Append random suffix until unique
        attempts = 0
        while True:
            attempts += 1
            if attempts > 100:
                raise ValueError("Could not generate a unique username after 100 attempts.")

            suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
            new_username = f"{username}-{suffix}"
            if not await self._user_dao.get_by_username(new_username):
                return new_username

    async def verify_access_token(self, token: str) -> TokenData:
        """
        Verify access token and return token data.

        Args:
            token: The access token string.
        Returns:
            TokenData: Validated token data.
        """
        return await verify_token(token, self._redis, token_type=TokenTypes.ACCESS.value)

    async def handle_google_oauth(self, user_info: dict) -> UserData:
        """
        Upsert user and identity for Google OAuth.

        Args:
            user_info (dict): Google user info from OAuth callback.
        Returns:
            UserData: The upserted or existing user data.
        """
        # 1. Try to find by Google ID
        user = await self._user_dao.get_by_google_sub(user_info["sub"])
        if user:
            return user

        # 2. Try to find by Email
        email = user_info.get("email")
        if email:
            user = await self._user_dao.get_by_email(email)
            if user:
                # If user exists and Google email is verified, link the account
                if user_info.get("email_verified"):
                    await self._user_dao.add_identity(user.id, user_info)
                    return user
                # If email matches but not verified, we let it fall through to create_user_oauth which will fail
                # with unique constraint error on email, which is safe.

        # 3. Create new user
        base_name = user_info.get("name") or user_info["email"].split("@")[0]
        username = await self._generate_unique_username(base_name)

        user_create = UserCreate(
            username=username,
            email=user_info["email"],
            password=None,
            full_name=user_info.get("name"),
            is_active=True,
        )
        user = await self._user_dao.create_user_oauth(user_create, user_info)
        logger.info("Created new user via Google OAuth: username=%s (user_id=%s)", user.username, user.id)
        return user

    async def _get_user_scopes(self, roles: list[RoleData]) -> list[str]:
        if not roles:
            return []

        scopes = set()
        for role in roles:
            for permission in role.permissions:
                scopes.add(permission.name)

        return list(scopes)

    async def issue_tokens_and_session(self, user: UserData, request: Request) -> LoginResponse:
        """
        Issue access and refresh tokens, create session in database, and return LoginResponse.

        Args:
            user (UserData): User data.
            request (Request): FastAPI request object.
        Returns:
            LoginResponse: Access and refresh tokens, user data.
        """
        scopes = await self._get_user_scopes(user.roles)
        token_data = {
            "sub": user.username,
            "id": str(user.id),
            "scopes": scopes,
            "token_version": user.token_version,
        }
        access_token_details = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        await self._user_dao.upsert_user_session(
            user_session_data=UserSessionCreate(
                jti=access_token_details["jti"],
                user_id=user.id,
                issued_at=get_utc_now(),
                expires_at=access_token_details["expires_at"],
                ip_address=request.client.host if request.client is not None else None,
                user_agent=request.headers.get("user-agent"),
            )
        )
        return LoginResponse(
            token=Token(access_token=access_token_details["token"], refresh_token=refresh_token),
            user=UserData.model_validate(user),
        )

    async def authenticate_oauth_user(self, user: UserData, request: Request) -> LoginResponse:
        """
        Issue access and refresh tokens for OAuth user.

        Args:
            user (UserData): The user data.
            request (Request): FastAPI request object.
        Returns:
            LoginResponse: Access and refresh tokens, user data.
        """
        response = await self.issue_tokens_and_session(user, request)
        logger.info("Authenticated OAuth user: %s (ID: %s)", user.username, user.id)
        return response

    async def authenticate_user(
        self, username: str, password: str, request: Request
    ) -> LoginResponse | TwoFactorChallengeResponse:
        """
        Authenticate user with username and password.

        Args:
            username: User username
            password: User password
            request: FastAPI request object

        Returns:
            LoginResponse | TwoFactorChallengeResponse: Token and user data, or 2FA challenge if enabled.
        """
        user = await self._user_dao.get_by_username(username)
        if not user or not verify_password(password, user.hashed_password):
            logger.warning("Failed login attempt for username: %s", username)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=trans("auth.invalid_credentials"),
                headers={"WWW-Authenticate": "Bearer"},
            )

        two_factor_data = await self._user_dao.get_two_factor(user.id)
        if two_factor_data and two_factor_data.get("is_enabled", False):
            challenge_token = uuid4().hex
            challenge_key = RedisKeys.TWO_FACTOR_CHALLENGE.format(token=challenge_token)
            await self._redis.set(
                challenge_key,
                str(user.id),
                ex=settings.TWO_FACTOR_CHALLENGE_EXPIRE_MINUTES * 60,
            )
            logger.info("2FA required for user: %s (ID: %s)", user.username, user.id)
            return TwoFactorChallengeResponse(two_factor_token=challenge_token)

        response = await self.issue_tokens_and_session(user, request)
        logger.info("User logged in successfully: %s (ID: %s)", user.username, user.id)
        return response

    async def refresh_token(self, refresh_token: str, request: Request) -> LoginResponse:
        """
        Refresh the access token using a refresh token.

        Args:
            refresh_token: The refresh token.
            request: FastAPI request object.

        Returns:
            LoginResponse: A new access token.
        """
        token_data = await verify_token(refresh_token, self._redis, token_type=TokenTypes.REFRESH.value)
        if token_data.id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=trans("auth.invalid_token_data"),
            )
        user = await self._user_dao.get_by_id(token_data.id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=trans("auth.invalid_refresh_user"),
            )

        # Check token version on refresh too?
        if user.token_version != token_data.token_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=trans("auth.token_version_mismatch"),
            )

        scopes = await self._get_user_scopes(user.roles)
        new_token_data = {
            "sub": user.username,
            "id": str(user.id),
            "scopes": scopes,
            "token_version": user.token_version,
        }
        access_token_details = create_access_token(new_token_data)
        new_refresh_token = create_refresh_token(new_token_data)

        await self._user_dao.upsert_user_session(
            user_session_data=UserSessionCreate(
                jti=access_token_details["jti"],
                user_id=user.id,
                issued_at=get_utc_now(),
                expires_at=access_token_details["expires_at"],
                ip_address=request.client.host if request.client is not None else None,
                user_agent=request.headers.get("user-agent"),
            )
        )

        logger.info("Refreshed access token for user: %s (ID: %s)", user.username, user.id)
        return LoginResponse(
            token=Token(access_token=access_token_details["token"], refresh_token=new_refresh_token),
            user=UserData.model_validate(user),
        )

    async def create_sudo_token_oauth(self, user: UserData) -> SudoTokenResponse:
        """
        Create a sudo token for OAuth user.

        Args:
            user (UserData): The user data.
            request (Request): FastAPI request object.
        Returns:
            SudoTokenResponse: Sudo token with expiration time.
        """
        token_data = {"sub": user.username, "id": str(user.id)}
        sudo_token = create_sudo_token(token_data)
        # Sudo token expires in SUDO_TOKEN_EXPIRE_MINUTES
        return SudoTokenResponse(sudo_token=sudo_token, expires_in=settings.SUDO_TOKEN_EXPIRE_MINUTES * 60)

    async def create_sudo_token_user(self, username: str, password: str) -> SudoTokenResponse:
        """
        Create a sudo token for regular user after password verification.

        Args:
            username: User username
            password: User password
            request (Request): FastAPI request object

        Returns:
            SudoTokenResponse: Sudo token with expiration time
        """
        user = await self._user_dao.get_by_username(username)
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=trans("auth.invalid_credentials"),
                headers={"WWW-Authenticate": "Bearer"},
            )

        token_data = {"sub": user.username, "id": str(user.id)}
        sudo_token = create_sudo_token(token_data)
        # Sudo token expires in SUDO_TOKEN_EXPIRE_MINUTES
        return SudoTokenResponse(sudo_token=sudo_token, expires_in=settings.SUDO_TOKEN_EXPIRE_MINUTES * 60)

    async def revoke_session(self, user_id: UUID, jti: str) -> None:
        """
        Revoke a user session by its JTI.

        Args:
            user_id: The user id
            jti: The JTI of the session to revoke

        Returns:
            None
        """
        ttl = await self._user_dao.revoke_user_session(user_id, jti)
        if ttl is None:
            logger.warning("Session not found for revocation: user_id=%s, jti=%s", user_id, jti)
            raise HTTPException(status_code=404, detail=trans("user.session_not_found"))
        await asyncio.gather(
            self._redis.set(f"blacklist:access:{jti}", 1, ex=ttl),
            self._redis.set(f"blacklist:refresh:{jti}", 1, ex=ttl),
        )
        logger.info("Revoked session for user_id=%s (jti=%s)", user_id, jti)

    async def update_password(self, user_id: UUID, password: str) -> None:
        """
        Update user password.

        Args:
            user_id: The user id
            password: The new password
        """
        hashed_password = get_password_hash(password)
        await self._user_dao.update_password(user_id, hashed_password)
        logger.info("Password updated for user_id=%s", user_id)

        user = await self._user_dao.get_by_id(user_id)
        if user:
            # Publish security event
            await event_bus.publish(
                ApplicationEvent(
                    event_name=EventNames.USER_PASSWORD_CHANGED,
                    payload={
                        "user_id": str(user_id),
                        "email": user.email,
                        "username": user.username,
                    },
                )
            )

    async def get_two_factor_status(self, user_id: UUID) -> TwoFactorStatusResponse:
        """
        Get current 2FA status for the user including remaining unused backup codes.

        Args:
            user_id (UUID): The user id

        Returns:
            TwoFactorStatusResponse: 2FA status response
        """
        record = await self._user_dao.get_two_factor(user_id)
        if not record or not record.get("is_enabled", False):
            return TwoFactorStatusResponse(is_enabled=False, backup_codes_remaining=0)

        backup_codes = record.get("backup_codes", [])
        remaining = sum(1 for c in backup_codes if not c.get("used", False))
        return TwoFactorStatusResponse(is_enabled=True, backup_codes_remaining=remaining)

    async def initiate_two_factor_setup(self, user: UserData) -> TwoFactorSetupResponse:
        """
        Initiate 2FA setup by generating a TOTP secret and QR code.
        Secret is temporarily cached in Redis until confirmed.

        Args:
            user (UserData): The user data

        Returns:
            TwoFactorSetupResponse: 2FA setup response
        """
        secret = generate_totp_secret()
        uri = generate_provisioning_uri(secret, name=user.email, issuer_name=settings.TWO_FACTOR_ISSUER_NAME)
        qr_code = generate_qr_code_svg(uri)

        encrypted = encrypt_secret(secret)
        setup_key = RedisKeys.TWO_FACTOR_SETUP.format(user_id=str(user.id))
        await self._redis.set(setup_key, encrypted, ex=600)

        logger.info("2FA setup initiated for user: %s (ID: %s)", user.username, user.id)
        return TwoFactorSetupResponse(
            secret=secret,
            qr_code=qr_code,
            otpauth_url=uri,
        )

    async def confirm_two_factor_setup(self, user: UserData, code: str) -> TwoFactorConfirmResponse:
        """
        Confirm 2FA setup with user-supplied OTP code.
        Generates and stores backup codes, activates 2FA in DB.

        Args:
            user (UserData): The user data
            code (str): The OTP code

        Returns:
            TwoFactorConfirmResponse: 2FA confirm response
        """
        setup_key = RedisKeys.TWO_FACTOR_SETUP.format(user_id=str(user.id))
        encrypted_secret = await self._redis.get(setup_key)
        if not encrypted_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=trans("auth.two_factor_setup_expired"),
            )

        if isinstance(encrypted_secret, bytes):
            encrypted_secret = encrypted_secret.decode("utf-8")

        secret = decrypt_secret(encrypted_secret)
        if not verify_totp(secret, code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=trans("auth.two_factor_invalid_code"),
            )

        plaintext_codes, hashed_records = generate_backup_codes(count=10)

        await self._user_dao.upsert_two_factor(
            user_id=user.id,
            secret_encrypted=encrypted_secret,
            backup_codes=hashed_records,
            is_enabled=True,
        )

        await self._redis.delete(setup_key)

        await event_bus.publish(
            ApplicationEvent(
                event_name=EventNames.USER_2FA_ENABLED,
                payload={
                    "user_id": str(user.id),
                    "email": user.email,
                    "username": user.username,
                },
            )
        )

        logger.info("2FA successfully enabled for user: %s (ID: %s)", user.username, user.id)
        return TwoFactorConfirmResponse(status="enabled", backup_codes=plaintext_codes)

    async def disable_two_factor(self, user: UserData, code: str) -> None:
        """
        Disable two-factor authentication for user. Requires code verification.

        Args:
            user (UserData): The user data
            code (str): Current OTP or backup recovery code

        Returns:
            None
        """
        record = await self._user_dao.get_two_factor(user.id)
        if not record or not record.get("is_enabled", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=trans("auth.two_factor_not_enabled"),
            )

        cleaned_code = code.strip()
        secret = decrypt_secret(record["secret_encrypted"])
        if not verify_totp(secret, cleaned_code):
            backup_codes = record.get("backup_codes", [])
            valid_backup, _ = verify_and_consume_backup_code(backup_codes, cleaned_code)
            if not valid_backup:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=trans("auth.two_factor_invalid_code_or_backup"),
                )

        await self._user_dao.disable_two_factor(user.id)
        await event_bus.publish(
            ApplicationEvent(
                event_name=EventNames.USER_2FA_DISABLED,
                payload={
                    "user_id": str(user.id),
                    "email": user.email,
                    "username": user.username,
                },
            )
        )
        logger.info("2FA disabled for user: %s (ID: %s)", user.username, user.id)

    async def regenerate_two_factor_backup_codes(self, user: UserData, code: str) -> list[str]:
        """
        Regenerate a fresh set of backup recovery codes. Requires code verification.

        Args:
            user (UserData): The user data
            code (str): Current OTP or backup recovery code

        Returns:
            list[str]: List of new backup codes
        """
        record = await self._user_dao.get_two_factor(user.id)
        if not record or not record.get("is_enabled", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=trans("auth.two_factor_not_enabled"),
            )

        cleaned_code = code.strip()
        secret = decrypt_secret(record["secret_encrypted"])
        if not verify_totp(secret, cleaned_code):
            backup_codes = record.get("backup_codes", [])
            valid_backup, _ = verify_and_consume_backup_code(backup_codes, cleaned_code)
            if not valid_backup:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=trans("auth.two_factor_invalid_code_or_backup"),
                )

        plaintext_codes, hashed_records = generate_backup_codes(count=10)
        await self._user_dao.update_two_factor_backup_codes(user.id, hashed_records)
        logger.info("Backup codes regenerated for user: %s (ID: %s)", user.username, user.id)
        return plaintext_codes

    async def _verify_2fa_code_or_backup(
        self, user_id: UUID, two_factor_data: dict[str, Any], cleaned_code: str
    ) -> None:
        """Verify 2FA code via TOTP with replay prevention, or consume a valid backup code."""
        secret = decrypt_secret(two_factor_data["secret_encrypted"])
        if verify_totp(secret, cleaned_code):
            slice_idx = int(time.time() // 30)
            replay_key = RedisKeys.TWO_FACTOR_REPLAY.format(user_id=str(user_id), timestamp_slice=slice_idx)
            if await self._redis.get(replay_key):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=trans("auth.two_factor_replay_detected"),
                )
            await self._redis.set(replay_key, "1", ex=60)
            return

        valid_backup, updated_codes = verify_and_consume_backup_code(
            two_factor_data.get("backup_codes", []), cleaned_code
        )
        if not valid_backup:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=trans("auth.two_factor_invalid_code_or_backup"),
            )
        await self._user_dao.update_two_factor_backup_codes(user_id, updated_codes)

    async def verify_two_factor_challenge(self, two_factor_token: str, code: str, request: Request) -> LoginResponse:
        """
        Verify 2FA login challenge using either TOTP code or backup code.
        On success, issues access & refresh tokens and user session.

        Args:
            two_factor_token (str): The two factor token
            code (str): The OTP code
            request (Request): FastAPI request object

        Returns:
            LoginResponse: Login response
        """
        challenge_key = RedisKeys.TWO_FACTOR_CHALLENGE.format(token=two_factor_token)
        user_id_raw = await self._redis.get(challenge_key)
        if not user_id_raw:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=trans("auth.two_factor_challenge_expired"),
            )

        user_id = UUID(user_id_raw.decode("utf-8") if isinstance(user_id_raw, bytes) else str(user_id_raw))

        two_factor_data = await self._user_dao.get_two_factor(user_id)
        if not two_factor_data or not two_factor_data.get("is_enabled", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=trans("auth.two_factor_not_enabled"),
            )

        await self._verify_2fa_code_or_backup(user_id, two_factor_data, code.strip())
        await self._redis.delete(challenge_key)

        user = await self._user_dao.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=trans("user.not_found"),
            )

        return await self.issue_tokens_and_session(user, request)

    async def impersonate_user(
        self,
        admin_user: UserData,
        target_user_id: UUID,
        reason: str,
        request: Request,
        duration_minutes: int = 30,
    ) -> ImpersonationResponse:
        """
        Start an impersonation session for a target user.

        Args:
            admin_user (UserData): The administrator performing the impersonation.
            target_user_id (UUID): The target user ID to impersonate.
            reason (str): Reason for impersonation (for auditing).
            request (Request): FastAPI request object.
            duration_minutes (int): Session duration in minutes. Defaults to 30.

        Returns:
            ImpersonationResponse: Access token and target user information.
        """
        # 1. Prevent nested/chained impersonation
        if CURRENT_IMPERSONATOR_ID.get():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=trans("auth.cannot_nest_impersonation"),
            )

        # 2. Prevent self-impersonation
        if admin_user.id == target_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=trans("auth.cannot_impersonate_self"),
            )

        # 3. Retrieve target user
        target_user = await self._user_dao.get_by_id(target_user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=trans("user.not_found"),
            )
        if not target_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=trans("auth.cannot_impersonate_inactive_user"),
            )

        # 4. Prevent impersonating superusers or administrators
        is_target_privileged = getattr(target_user, "is_superuser", False) or any(
            r.name in ["Super Admin", "Admin"] for r in target_user.roles
        )
        if is_target_privileged:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=trans("auth.cannot_impersonate_admin"),
            )

        # 5. Build token payload with RFC 8693 actor claim
        scopes = await self._get_user_scopes(target_user.roles)
        token_data = {
            "sub": target_user.username,
            "id": str(target_user.id),
            "scopes": scopes,
            "token_version": target_user.token_version,
            "is_impersonation": True,
            "act": {
                "id": str(admin_user.id),
                "sub": admin_user.username,
            },
        }

        # 6. Issue bounded access token (no refresh token)
        token_details = create_impersonation_token(token_data, expire_minutes=duration_minutes)

        # 7. Store ephemeral session in Redis with TTL
        session_key = RedisKeys.IMPERSONATION_SESSION.format(jti=token_details["jti"])
        session_meta = {
            "admin_id": str(admin_user.id),
            "admin_username": admin_user.username,
            "target_user_id": str(target_user.id),
            "target_username": target_user.username,
            "reason": reason,
            "issued_at": get_utc_now().isoformat(),
            "expires_at": token_details["expires_at"].isoformat(),
        }
        await self._redis.set(session_key, json.dumps(session_meta), ex=duration_minutes * 60)

        # 8. Record operational audit log
        AuditLogger.log(
            action=AuditActions.USER_IMPERSONATION_START,
            resource=AuditResources.USER,
            resource_id=str(target_user.id),
            actor_id=admin_user.id,
            impersonator_id=admin_user.id,
            details={
                "reason": reason,
                "target_username": target_user.username,
                "jti": token_details["jti"],
                "duration_minutes": duration_minutes,
            },
            request=request,
        )

        # 9. Publish domain event
        await event_bus.publish(
            ApplicationEvent(
                event_name=EventNames.USER_IMPERSONATION_STARTED,
                payload={
                    "admin_id": str(admin_user.id),
                    "target_user_id": str(target_user.id),
                    "reason": reason,
                    "jti": token_details["jti"],
                },
            )
        )

        return ImpersonationResponse(
            token=Token(access_token=token_details["token"], refresh_token=""),  # nosec B106
            target_user=target_user,
            impersonator=ImpersonatorInfo(id=admin_user.id, username=admin_user.username),
            expires_at=token_details["expires_at"],
        )

    async def stop_impersonation(self, jti: str, admin_id: UUID) -> None:
        """
        Terminate an active impersonation session and blacklist the token.

        Args:
            jti (str): The JWT ID of the impersonation token.
            admin_id (UUID): The admin user ID.
        """
        # 1. Blacklist token in Redis immediately
        blacklist_key = f"blacklist:access:{jti}"
        await self._redis.set(blacklist_key, "1", ex=3600)

        # 2. Retrieve & delete ephemeral session
        session_key = RedisKeys.IMPERSONATION_SESSION.format(jti=jti)
        session_raw = await self._redis.get(session_key)
        target_id: str | None = None
        if session_raw:
            meta = json.loads(session_raw)
            target_id = meta.get("target_user_id")
            await self._redis.delete(session_key)

        # 3. Log audit event
        AuditLogger.log(
            action=AuditActions.USER_IMPERSONATION_STOP,
            resource=AuditResources.USER,
            resource_id=target_id or str(admin_id),
            actor_id=admin_id,
            impersonator_id=admin_id,
            details={"jti": jti, "target_user_id": target_id},
        )

        # 4. Publish domain event
        await event_bus.publish(
            ApplicationEvent(
                event_name=EventNames.USER_IMPERSONATION_STOPPED,
                payload={
                    "admin_id": str(admin_id),
                    "target_user_id": target_id,
                    "jti": jti,
                },
            )
        )


async def get_auth_service(
    user_dao: UserDAO = Depends(get_user_dao),
    role_dao: RoleDAO = Depends(get_role_dao),
    redis: Redis = Depends(get_redis),
) -> AuthService:
    """
    Dependency to get AuthService instance.

    Args:
        user_dao (UserDAO): The User Data Access Object.
        role_dao (RoleDAO): The Role Data Access Object.
        redis (Redis): The Redis client.

    Returns:
        AuthService: The Auth Service.
    """
    return AuthService(user_dao=user_dao, role_dao=role_dao, redis=redis)
