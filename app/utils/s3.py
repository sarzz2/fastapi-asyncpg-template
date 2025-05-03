import logging
import uuid
from mimetypes import guess_type

from botocore.exceptions import NoCredentialsError, PartialCredentialsError
from fastapi import APIRouter, File, Request, UploadFile
from starlette.responses import StreamingResponse

from app.core.aws_localstack import s3_client
from app.core.config import settings

router = APIRouter()
log = logging.getLogger("fastapi")


@router.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    try:
        unique_key = f"{uuid.uuid4()}_{file.filename.replace(' ', '_')}"
        s3_client.upload_fileobj(
            file.file, settings.AWS_BUCKET_NAME, unique_key, ExtraArgs={"Tagging": "status=temporary"}
        )
        return {
            "url": f"{str(request.base_url)[:-1]}/files/{unique_key}",
            "message": "File uploaded successfully",
        }
    except (NoCredentialsError, PartialCredentialsError):
        return {"error": "Credentials not available"}


@router.post("/commit-upload/{file_url}")
async def commit_upload(file_url: str):
    # Extract the unique_key from the URL (assuming it's in the path)
    unique_key = file_url.split("/")[-1]
    # Remove or update the temporary tag on the S3 object
    s3_client.put_object_tagging(
        Bucket=settings.AWS_BUCKET_NAME, Key=unique_key, Tagging={"TagSet": [{"Key": "status", "Value": "permanent"}]}
    )
    return {"message": "Upload committed"}


@router.get("/files/{unique_key}")
async def get_file(unique_key: str):
    try:
        # Get the object from S3
        response = s3_client.get_object(Bucket=settings.AWS_BUCKET_NAME, Key=unique_key)
        # Guess the content type of the file (like image/jpeg, image/png)
        content_type, _ = guess_type(unique_key.split("_", 1)[1])  # Extract original filename from unique key
        if not content_type:
            content_type = "application/octet-stream"
        return StreamingResponse(response["Body"], media_type=content_type)
    except s3_client.exceptions.NoSuchKey:
        return {"error": "File not found"}


@router.delete("/files/{unique_key}")
async def delete_file(unique_key: str):
    try:
        s3_client.delete_object(Bucket=settings.AWS_BUCKET_NAME, Key=unique_key)
        return {"message": f"File '{unique_key}' deleted successfully"}
    except s3_client.exceptions.NoSuchKey:
        return {"error": "File not found"}
