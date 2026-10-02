class RedisKeys:
    """
    Centralized Redis key patterns used across the application.
    """

    OAUTH_STATE_GOOGLE = "oauth:state:google:{state}"

    # Roles Cache (Hash)
    ROLES_CACHE = "roles_cache"
    ROLE_FIELD_ALL = "all:{limit}:{cursor}"
    ROLE_FIELD_BY_ID = "{role_id}"

    # App Version Cache (String)
    APP_VERSION_CACHE = "app_version:{platform}"
    APP_VERSIONS_ALL_CACHE = "app_versions:all"

    # Idempotency Layer
    IDEMPOTENCY_LOCK = "idempotency:lock:{key}"
    IDEMPOTENCY_RESPONSE = "idempotency:response:{key}"

    # Two-Factor Authentication
    TWO_FACTOR_SETUP = "2fa:setup:{user_id}"
    TWO_FACTOR_CHALLENGE = "2fa:challenge:{token}"
    TWO_FACTOR_REPLAY = "2fa:replay:{user_id}:{timestamp_slice}"

    # API Key Cache (String)
    API_KEY_CACHE = "api_key:cache:{hashed_key}"

    # User Impersonation
    IMPERSONATION_SESSION = "impersonation:session:{jti}"

    # System Configuration Cache (String)
    SYSTEM_CONFIG_CACHE = "system_config:singleton"

    # Notifications (Pub/Sub & SSE)
    NOTIFICATION_USER_CHANNEL = "notifications:user:{user_id}"
    NOTIFICATION_BROADCAST_CHANNEL = "notifications:broadcast"
