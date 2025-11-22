from typing import Dict, Optional

from pydantic import BaseModel


class S3UploadUrlRequest(BaseModel):
    """Request model for generating a presigned URL for uploading a file to S3."""

    filename: str
    content_type: Optional[str] = None


class S3UploadUrlResponse(BaseModel):
    """Response model for generating a presigned URL for uploading a file to S3."""

    upload_url: str
    fields: Dict[str, str]
    key: str
    expires_in: int


class S3DeleteFileRequest(BaseModel):
    """Request model for deleting a file from S3."""

    key: str
