"""HTTP clients for Marker document parsing.

This module contains two clients:
- DatalabMarkerClient: Calls the Datalab managed API at https://www.datalab.to/api/v1/marker
  This is the ACTIVE client used for all ingestion.
- RemoteMarkerClient: (DISABLED) Legacy client that called a self-hosted Modal endpoint.
  Kept for reference but no longer used in production.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from marker.debug import save_marker_output

logger = logging.getLogger(__name__)

# ─── Default constants for the Datalab managed API ──────────────────────────

DATALAB_API_URL = "https://www.datalab.to/api/v1/marker"
DATALAB_DEFAULT_POLL_INTERVAL = 5  # seconds between status checks
DATALAB_DEFAULT_TIMEOUT = 600  # total seconds before giving up


class DatalabMarkerClient:
    """Call the Datalab managed Marker API (async/polling) and return the JSON tree.

    Datalab's API is asynchronous:
      1. POST the file to /api/v1/marker  →  returns { "request_check_url": "..." }
      2. Poll request_check_url until status == "complete"
      3. The completed response contains the document JSON tree

    The returned payload has the same shape that marker_tree_mapper.py expects
    (document root with block_type, children, bbox, html fields).
    """

    def __init__(
        self,
        api_key: str,
        debug_root: str | Path | None = None,
        *,
        output_format: str = "json",
        use_llm: bool = True,
        mode: str = "accurate",
        poll_interval: int = DATALAB_DEFAULT_POLL_INTERVAL,
        timeout: int = DATALAB_DEFAULT_TIMEOUT,
    ):
        if not api_key:
            raise ValueError(
                "DATALAB_API_KEY is required. Get one at https://www.datalab.to"
            )
        self.api_key = api_key
        self.debug_root = debug_root
        self.output_format = output_format
        self.use_llm = use_llm
        self.mode = mode
        self.poll_interval = poll_interval
        self.timeout = timeout

    async def parse(self, file_path: str | Path) -> Any:
        """Submit a PDF to Datalab, poll until complete, return the JSON tree."""
        file_path = Path(file_path)
        pdf_bytes = file_path.read_bytes()

        logger.info(
            "Submitting %s (%.1f MB) to Datalab Marker API (mode=%s, use_llm=%s)",
            file_path.name,
            len(pdf_bytes) / 1_048_576,
            self.mode,
            self.use_llm,
        )

        headers = {"X-Api-Key": self.api_key}

        # ── Step 1: Submit the file ─────────────────────────────────────
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            submit_response = await client.post(
                DATALAB_API_URL,
                headers=headers,
                files={"file": (file_path.name, pdf_bytes, "application/pdf")},
                data={
                    "output_format": self.output_format,
                    "use_llm": str(self.use_llm).lower(),
                    "mode": self.mode,
                },
            )

        submit_response.raise_for_status()
        submit_data = submit_response.json()

        request_check_url = submit_data.get("request_check_url")
        if not request_check_url:
            raise RuntimeError(
                f"Datalab did not return a request_check_url. Response: {submit_data}"
            )

        logger.info(
            "Datalab accepted %s — polling %s",
            file_path.name,
            request_check_url,
        )

        # ── Step 2: Poll until complete ─────────────────────────────────
        data = await self._poll_until_complete(request_check_url, headers, file_path.name)

        save_marker_output(file_path, data, debug_root=self.debug_root)
        return data

    async def _poll_until_complete(
        self,
        check_url: str,
        headers: dict[str, str],
        filename: str,
    ) -> dict[str, Any]:
        """Poll the request_check_url until the job finishes or times out."""
        elapsed = 0

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            while elapsed < self.timeout:
                await asyncio.sleep(self.poll_interval)
                elapsed += self.poll_interval

                response = await client.get(check_url, headers=headers)
                response.raise_for_status()
                result = response.json()

                status = result.get("status")

                if status == "complete":
                    logger.info(
                        "Datalab completed %s after ~%ds — %d top-level keys",
                        filename,
                        elapsed,
                        len(result),
                    )
                    return result

                if status == "failed":
                    error_msg = result.get("error", "unknown error")
                    raise RuntimeError(
                        f"Datalab Marker failed for {filename}: {error_msg}"
                    )

                logger.debug(
                    "Datalab status for %s: %s (elapsed %ds)",
                    filename,
                    status,
                    elapsed,
                )

        raise TimeoutError(
            f"Datalab Marker timed out after {self.timeout}s for {filename}. "
            f"Last poll URL: {check_url}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# DISABLED — Legacy Modal-hosted Marker client
# ─────────────────────────────────────────────────────────────────────────────
#
# The class below was used when Marker was self-hosted on Modal at:
#   https://asimsiddiqui-you--datalab-marker-modal-demo-markermodald-d2149d.modal.run/convert
#
# We have since switched to the Datalab managed API (DatalabMarkerClient above).
# This code is kept for reference in case we ever need to revert to a
# self-hosted deployment, but it is NOT imported or used anywhere.
#
# To re-enable:
#   1. Uncomment this class
#   2. Update __init__.py to export RemoteMarkerClient
#   3. Update parsers/marker_client.py to use RemoteMarkerClient
#   4. Set MARKER_ENDPOINT_URL in .env to your Modal endpoint
#
# class RemoteMarkerClient:
#     """Call the hosted Marker /convert endpoint and return the raw JSON response.
#
#     DISABLED — replaced by DatalabMarkerClient which calls the managed Datalab API.
#     This was used with the self-hosted Modal deployment.
#     """
#
#     def __init__(
#         self,
#         endpoint_url: str,
#         debug_root: str | Path | None = None,
#         *,
#         output_format: str = "json",
#         use_llm: bool = False,
#     ):
#         self.endpoint_url = endpoint_url.strip()
#         self.debug_root = debug_root
#         self.output_format = output_format
#         self.use_llm = use_llm
#
#     async def parse(self, file_path: str | Path) -> Any:
#         file_path = Path(file_path)
#         pdf_bytes = file_path.read_bytes()
#
#         logger.info(
#             "Sending %s (%.1f MB) to Marker at %s",
#             file_path.name,
#             len(pdf_bytes) / 1_048_576,
#             self.endpoint_url,
#         )
#
#         async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
#             response = await client.post(
#                 self.endpoint_url,
#                 files={"file": (file_path.name, pdf_bytes, "application/pdf")},
#                 data={
#                     "output_format": self.output_format,
#                     "use_llm": "true" if self.use_llm else "false",
#                 },
#             )
#
#         response.raise_for_status()
#         data = response.json()
#
#         if isinstance(data, dict):
#             logger.info(
#                 "Marker returned raw JSON with %d top-level keys for %s",
#                 len(data),
#                 file_path.name,
#             )
#         else:
#             logger.info(
#                 "Marker returned raw JSON of type %s for %s",
#                 type(data).__name__,
#                 file_path.name,
#             )
#
#         save_marker_output(file_path, data, debug_root=self.debug_root)
#         return data
# ─────────────────────────────────────────────────────────────────────────────
