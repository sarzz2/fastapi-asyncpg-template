import logging
import mimetypes
import uuid

from botocore.exceptions import ClientError

from api.core.aws_localstack import s3_client
from api.core.config import settings

log = logging.getLogger(__name__)


class S3Service:
    """
    Service class for handling AWS S3 operations.
    """

    def __init__(self) -> None:
        self.bucket_name = settings.AWS_BUCKET_NAME
        self.region_name = settings.S3_REGION_NAME
        self.endpoint_url = settings.S3_ENDPOINT_URL

    def generate_presigned_url(self, filename: str, content_type: str | None = None, expiration: int = 300) -> dict:
        """
        Generate a presigned URL to share an S3 object.

        Args:
            filename (str): The name of the file to upload.
            content_type (str | None): The content type of the file.
            expiration (int): Time in seconds for the presigned URL to remain valid.

        Returns:
            dict: A dictionary containing the upload URL, key, expiration time, and required headers.

        Raises:
            ClientError: If an error occurs while generating the URL.
        """
        # Generate a unique key for the file
        key = f"{uuid.uuid4()}/{filename}"

        try:
            if not content_type:
                content_type, _ = mimetypes.guess_type(filename)

            if content_type not in settings.ALLOWED_CONTENT_TYPES:
                raise ValueError(
                    f"Content-Type {content_type} is not allowed. "
                    f"Allowed types: {', '.join(settings.ALLOWED_CONTENT_TYPES)}"
                )

            # Conditions for the policy
            conditions = [
                ["content-length-range", 0, 5242880],  # 0 to 5MB
                {"Content-Type": content_type},  # Exact match for content type
                {"x-amz-tagging": "status=temporary"},  # Must have this tag
            ]

            response = s3_client.generate_presigned_post(
                Bucket=self.bucket_name,
                Key=key,
                Fields={
                    "Content-Type": content_type,
                    "x-amz-tagging": "status=temporary",
                },
                Conditions=conditions,
                ExpiresIn=expiration,
            )

            return {
                "upload_url": response["url"],
                "fields": response["fields"],
                "key": key,
                "expires_in": expiration,
            }
        except ClientError as e:
            log.error("Error generating presigned POST: %s", e)
            raise e

    def delete_file(self, key: str) -> None:
        """
        Delete a file from an S3 bucket.

        Args:
            key (str): The key of the file to delete.

        Raises:
            ClientError: If an error occurs while deleting the file.
        """
        try:
            s3_client.delete_object(Bucket=self.bucket_name, Key=key)
            log.info("Deleted file: %s", key)
        except ClientError as e:
            log.error("Error deleting file %s: %s", key, e)
            raise e

    def get_file_url(self, key: str, presigned: bool = True, expiration: int = 3600) -> str:
        """
        Get the URL for a file.

        Args:
            key (str): The key of the file.
            presigned (bool): If True, returns a presigned URL. If False, returns a public URL.
            expiration (int): Expiration time in seconds for the presigned URL.

        Returns:
            str: The URL of the file.
        """
        if presigned:
            try:
                params = {"Bucket": self.bucket_name, "Key": key, "ResponseContentDisposition": "inline"}
                url = s3_client.generate_presigned_url(
                    ClientMethod="get_object",
                    Params=params,
                    ExpiresIn=expiration,
                )
                return str(url)
            except ClientError as e:
                log.error("Error generating presigned get URL: %s", e)
                return ""
        else:
            if "localhost" in self.endpoint_url:
                return f"{self.endpoint_url}/{self.bucket_name}/{key}"
            return f"https://{self.bucket_name}.s3.{self.region_name}.amazonaws.com/{key}"


async def get_s3_service() -> S3Service:
    """
    Get the S3 service.
    """
    return S3Service()
