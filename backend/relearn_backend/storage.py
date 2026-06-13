"""Object storage for the gateway: upload PDFs, presign for the visualizer.

Mirrors the AI service's key layout (pdfs/{sha256}.pdf). Presigned GET URLs let
the browser fetch PDFs directly without proxying bytes through the backend.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import boto3
from botocore.config import Config

from relearn_backend.config import get_settings

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


async def put_pdf(checksum: str, data: bytes) -> str:
    key = pdf_key(checksum)

    def _put() -> None:
        _client().put_object(
            Bucket=get_settings().s3_bucket, Key=key, Body=data, ContentType="application/pdf"
        )

    await asyncio.get_running_loop().run_in_executor(None, _put)

    # durable host mirror of the raw PDF (matches ai/storage key layout)
    base = get_settings().local_cache_dir
    if base:
        p = Path(base) / key

        def _mirror() -> None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

        try:
            await asyncio.get_running_loop().run_in_executor(None, _mirror)
        except OSError as e:
            logger.warning("local mirror write failed for %s: %s", key, e)
    return key


async def presign_get(key: str) -> str:
    s = get_settings()

    def _sign() -> str:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": s.s3_bucket, "Key": key},
            ExpiresIn=s.signed_url_ttl_s,
        )

    return await asyncio.get_running_loop().run_in_executor(None, _sign)
