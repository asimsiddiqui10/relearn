"""Datalab managed Marker API client (ported from v1).

Async submit-then-poll. The caller (pipeline) handles the S3 parse cache —
this module only talks to Datalab.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from relearn_ai.observability import observe

logger = logging.getLogger(__name__)

DATALAB_API_URL = "https://www.datalab.to/api/v1/marker"
POLL_INTERVAL_S = 5
TIMEOUT_S = 600


class DatalabError(RuntimeError):
    pass


@observe(name="datalab_parse")
async def parse_pdf(
    pdf_bytes: bytes,
    filename: str,
    *,
    api_key: str,
    use_llm: bool = True,
    mode: str = "accurate",
) -> dict[str, Any]:
    """Submit a PDF to Datalab, poll until complete, return the raw JSON payload."""
    if not api_key:
        raise DatalabError("DATALAB_API_KEY is required — get one at https://www.datalab.to")

    headers = {"X-Api-Key": api_key}
    logger.info(
        "Submitting %s (%.1f MB) to Datalab (mode=%s, use_llm=%s)",
        filename, len(pdf_bytes) / 1_048_576, mode, use_llm,
    )

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        submit = await client.post(
            DATALAB_API_URL,
            headers=headers,
            files={"file": (filename, pdf_bytes, "application/pdf")},
            data={"output_format": "json", "use_llm": str(use_llm).lower(), "mode": mode},
        )
    submit.raise_for_status()
    check_url = submit.json().get("request_check_url")
    if not check_url:
        raise DatalabError(f"Datalab did not return a request_check_url: {submit.json()}")

    elapsed = 0
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        while elapsed < TIMEOUT_S:
            await asyncio.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S
            resp = await client.get(check_url, headers=headers)
            resp.raise_for_status()
            result = resp.json()
            status = result.get("status")
            if status == "complete":
                logger.info("Datalab completed %s after ~%ds", filename, elapsed)
                return result
            if status == "failed":
                raise DatalabError(f"Datalab failed for {filename}: {result.get('error')}")

    raise TimeoutError(f"Datalab timed out after {TIMEOUT_S}s for {filename}")
