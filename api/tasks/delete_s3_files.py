import logging
from datetime import datetime, timedelta

from botocore.exceptions import ClientError

from api.core.aws_localstack import s3_client
from api.core.config import settings

log = logging.getLogger("apscheduler")


async def delete_stagnant_temporary_files() -> None:
    """
    Deletes temporary files in the S3 bucket that have been stagnant for more than 15 minutes.
    A file is considered temporary if it has the tag 'status' set to 'temporary'."""
    try:
        # List objects in the bucket
        response = s3_client.list_objects_v2(Bucket=settings.AWS_BUCKET_NAME)
        if "Contents" not in response:
            log.info("No files found in the bucket.")
            return

        for obj in response["Contents"]:
            key = obj["Key"]
            # Get object tagging
            tagging = s3_client.get_object_tagging(Bucket=settings.AWS_BUCKET_NAME, Key=key)
            tags = {tag["Key"]: tag["Value"] for tag in tagging["TagSet"]}

            # Check if the file has the temporary status
            if tags.get("status") == "temporary":
                # Check if the file is stagnant for more than 15 minutes
                last_modified = obj["LastModified"]
                if datetime.now(last_modified.tzinfo) - last_modified > timedelta(minutes=15):
                    s3_client.delete_object(Bucket=settings.AWS_BUCKET_NAME, Key=key)
                    log.info("Deleted stagnant temporary file: %s", key)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        log.error("An S3 client error occurred (%s) while deleting stagnant files: %s", error_code, e)
