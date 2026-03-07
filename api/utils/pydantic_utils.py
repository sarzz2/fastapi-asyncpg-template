import re
from typing import Annotated, Any, Optional

from pydantic import BeforeValidator

from api.apps.s3.v0.services.s3 import S3Service


def validate_password_strength(v: Any) -> Any:
    """
    Validate password strength.

    Args:
        v (Any): The password to validate.

    Returns:
        Any: The validated password.

    Raises:
        ValueError: If the password is not strong enough.
    """
    if not isinstance(v, str):
        return v
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain a lowercase letter")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain an uppercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain a number")
    if not re.search(r"[@$!%*?&]", v):
        raise ValueError("Password must contain a special character (@$!%*?&)")
    return v


# Strong password requiring at least 8 chars, 1 uppercase, 1 lowercase, 1 number, and 1 special character
StrongPassword = Annotated[str, BeforeValidator(validate_password_strength)]


_s3_service = S3Service()


def generate_file_url(key: Optional[str], presigned: bool = True) -> Optional[str]:
    """
    Generate a URL for a given S3 key.

    Args:
        key (Optional[str]): The S3 key.
        presigned (bool): Whether to generate a presigned URL.

    Returns:
        Optional[str]: The generated URL or None if key is missing.
    """
    if not key:
        return None
    return _s3_service.get_file_url(key, presigned=presigned)
