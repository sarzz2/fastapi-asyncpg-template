from typing import Annotated, Optional

from pydantic import StringConstraints

from api.apps.s3.v0.services.s3 import S3Service

# Strong password requiring at least 8 chars, 1 uppercase, 1 lowercase, 1 number, and 1 special character
StrongPassword = Annotated[
    str,
    StringConstraints(min_length=8, pattern=r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$"),
]


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
