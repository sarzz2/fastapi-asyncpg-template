from enum import Enum


class EventNames(str, Enum):
    """
    Centralized constants for all application events.
    Using an Enum containing strings enables type-safety and eliminates spelling errors
    when routing events across detached modules.
    """

    USER_CREATED = "user.created"
    USER_PASSWORD_CHANGED = "user.password.changed"  # nosec B105
    USER_ROLE_ASSIGNED = "user.role.assigned"
