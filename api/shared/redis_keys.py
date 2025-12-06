class RedisKeys:
    """
    Centralized Redis key patterns used across the application.
    """

    OAUTH_STATE_GOOGLE = "oauth:state:google:{state}"

    # Roles Cache (Hash)
    ROLES_CACHE = "roles_cache"
    ROLE_FIELD_ALL = "all"
    ROLE_FIELD_BY_ID = "{role_id}"
