"""S3-compatible photo storage via MinIO / AWS S3."""

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
            endpoint_url=f"{'https' if settings.minio_secure else 'http'}://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 1}),
        )
        try:
            _client.head_bucket(Bucket=settings.minio_bucket)
        except ClientError:
            _client.create_bucket(Bucket=settings.minio_bucket)
    return _client


def _upload_sync(image_bytes: bytes, content_type: str) -> str | None:
    key = f"pets/{uuid.uuid4()}.jpg"
    client = _get_client()
    client.put_object(
        Bucket=settings.minio_bucket,
        Key=key,
        Body=io.BytesIO(image_bytes),
        ContentType=content_type,
    )
    scheme = "https" if settings.minio_secure else "http"
    return f"{scheme}://{settings.minio_endpoint}/{settings.minio_bucket}/{key}"


async def upload_photo(image_bytes: bytes, content_type: str = "image/jpeg") -> str | None:
    """Uploads photo and returns public URL. Returns None if storage is unavailable.

    Runs boto3 (blocking) in a thread pool so it never stalls the event loop.
    """
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _upload_sync, image_bytes, content_type)
    except Exception as exc:
        _log.warning("Photo upload failed (storage unavailable): %s", exc)
        return None
