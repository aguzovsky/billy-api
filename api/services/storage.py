"""S3-compatible photo storage via MinIO / AWS S3."""

from __future__ import annotations

import io
import uuid

import boto3
from botocore.exceptions import ClientError

from api.core.config import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=f"{'https' if settings.minio_secure else 'http'}://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )
        # Ensure bucket exists
        try:
            _client.head_bucket(Bucket=settings.minio_bucket)
        except ClientError:
            _client.create_bucket(Bucket=settings.minio_bucket)
    return _client


async def upload_photo(image_bytes: bytes, content_type: str = "image/jpeg") -> str | None:
    """Uploads photo and returns public URL. Returns None if storage is unavailable."""
    try:
        key = f"pets/{uuid.uuid4()}.jpg"
        client = _get_client()
        client.put_object(
            Bucket=settings.minio_bucket,
            Key=key,
            Body=io.BytesIO(image_bytes),
            ContentType=content_type,
        )
        endpoint = settings.minio_endpoint
        scheme = "https" if settings.minio_secure else "http"
        return f"{scheme}://{endpoint}/{settings.minio_bucket}/{key}"
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Photo upload failed (storage unavailable): %s", exc)
        return None
