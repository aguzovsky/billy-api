"""Photo storage via AWS S3."""

from __future__ import annotations

import asyncio
import io
import logging
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from api.core.config import settings

_log = logging.getLogger(__name__)
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            region_name=settings.aws_s3_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            config=Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 2}),
        )
    return _client


def _upload_sync(image_bytes: bytes, content_type: str) -> str | None:
    key = f"pets/{uuid.uuid4()}.jpg"
    client = _get_client()
    client.put_object(
        Bucket=settings.aws_s3_bucket,
        Key=key,
        Body=io.BytesIO(image_bytes),
        ContentType=content_type,
    )
    return f"https://{settings.aws_s3_bucket}.s3.{settings.aws_s3_region}.amazonaws.com/{key}"


async def upload_photo(image_bytes: bytes, content_type: str = "image/jpeg") -> str | None:
    """Uploads photo to S3 and returns public URL. Returns None if storage is unavailable.

    Runs boto3 (blocking) in a thread pool so it never stalls the event loop.
    """
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _upload_sync, image_bytes, content_type)
    except Exception as exc:
        _log.warning("Photo upload failed (storage unavailable): %s", exc)
        return None
