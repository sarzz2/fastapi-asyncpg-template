from fastapi import APIRouter, Depends, HTTPException, status

from api.apps.common.v0.schemas.s3 import S3UploadUrlRequest, S3UploadUrlResponse
from api.apps.common.v0.service.s3 import S3Service, get_s3_service
from api.apps.user.v0.schemas.user import UserData
from api.core.dependencies import get_current_user
from api.core.i18n import trans

router = APIRouter()


@router.post("/upload-url", response_model=S3UploadUrlResponse)
def generate_upload_url(
    request: S3UploadUrlRequest,
    s3_service: S3Service = Depends(get_s3_service),
    _current_user: UserData = Depends(get_current_user),
) -> S3UploadUrlResponse:
    """
    Generate a presigned URL for uploading a file to S3.
    """
    try:
        result = s3_service.generate_presigned_url(filename=request.filename, content_type=request.content_type)
        return S3UploadUrlResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=trans("s3.upload_url_failed").format(error=str(e)),
        ) from e


@router.delete("/file", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    key: str,
    s3_service: S3Service = Depends(get_s3_service),
    _current_user: UserData = Depends(get_current_user),
) -> None:
    """
    Delete a file from S3.
    """
    try:
        s3_service.delete_file(key)
        return
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=trans("s3.delete_failed").format(error=str(e))
        ) from e


@router.get("/file/{key:path}")
def get_file(key: str, s3_service: S3Service = Depends(get_s3_service)) -> str:
    """
    Get a file from S3.
    """
    try:
        return s3_service.get_file_url(key)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=trans("s3.get_failed").format(error=str(e))
        ) from e
