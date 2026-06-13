"""S3-compatible object storage (MinIO in dev, AWS S3 in prod).

Key layout (spec/05):
    pdfs/{sha256}.pdf      original uploads — written once, never deleted
    parses/{sha256}.json   raw Marker output — the global parse cache
    images/{sha256}/{n}    images extracted during ingestion
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from relearn_ai.config import get_settings

logger = logging.getLogger(__name__)


def _client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        config=Config(signature_version="s3v4"),
    )


def pdf_key(checksum: str) -> str:
    return f"pdfs/{checksum}.pdf"


def parse_key(checksum: str) -> str:
    return f"parses/{checksum}.json"


def image_key(checksum: str, n: int, ext: str = "png") -> str:
    return f"images/{checksum}/{n}.{ext}"


def _local_path(key: str) -> Path | None:
    """Host-filesystem mirror path for an S3 key, or None when disabled."""
    base = get_settings().local_cache_dir
    return Path(base) / key if base else None


async def get_bytes(key: str) -> bytes | None:
    def _get() -> bytes | None:
        try:
            resp = _client().get_object(Bucket=get_settings().s3_bucket, Key=key)
            return resp["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    data = await asyncio.get_running_loop().run_in_executor(None, _get)
    if data is not None:
        return data
    # S3 miss → fall back to the durable host mirror so re-ingestion never
    # re-parses (e.g. after a MinIO volume wipe).
    p = _local_path(key)
    if p is not None and p.exists():
        logger.info("S3 miss for %s — served from local mirror %s", key, p)
        return await asyncio.get_running_loop().run_in_executor(None, p.read_bytes)
    return None


async def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    def _put() -> None:
        _client().put_object(
            Bucket=get_settings().s3_bucket, Key=key, Body=data, ContentType=content_type
        )

    await asyncio.get_running_loop().run_in_executor(None, _put)
    await _mirror_local(key, data)


async def _mirror_local(key: str, data: bytes) -> None:
    """Best-effort write to the host mirror — never fails an already-committed
    S3 put (so a paid Datalab parse is never lost to a filesystem hiccup)."""
    p = _local_path(key)
    if p is None:
        return

    def _write() -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    try:
        await asyncio.get_running_loop().run_in_executor(None, _write)
    except OSError as e:
        logger.warning("local mirror write failed for %s: %s", key, e)


async def get_json(key: str) -> Any | None:
    raw = await get_bytes(key)
    return json.loads(raw) if raw is not None else None


async def put_json(key: str, payload: Any) -> None:
    await put_bytes(key, json.dumps(payload).encode(), content_type="application/json")
