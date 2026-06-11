"""Langfuse tracing — no-op without keys (v1 tracing.py pattern).

`@observe` wraps functions in Langfuse spans when LANGFUSE_* keys are set;
otherwise it returns the function unchanged. Services never check whether
tracing is enabled.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_langfuse = None
_observe = None


def _init() -> None:
    global _langfuse, _observe
    try:
        from relearn_ai.config import get_settings

        settings = get_settings()
        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            return

        from langfuse import Langfuse, observe as lf_observe

        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host or None,
        )
        _observe = lf_observe
        logger.info("Langfuse tracing enabled")
    except ImportError:
        logger.info("langfuse package not installed — tracing disabled")
    except Exception as exc:
        logger.warning("Langfuse init failed (%s) — tracing disabled", exc)


_init()


def get_langfuse():
    return _langfuse


def observe(*args: Any, **kwargs: Any):
    """@observe / @observe(name=...) — no-op decorator when tracing is off."""
    if _observe is None:
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def _noop(fn):
            return fn

        return _noop
    return _observe(*args, **kwargs)
