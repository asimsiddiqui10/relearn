"""Langfuse observability integration.

Provides a shared Langfuse client and the @observe decorator.
All calls are no-ops when LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Mapping, Sequence
from typing import Any

logger = logging.getLogger(__name__)

_langfuse = None
_observe = None


def _init():
    global _langfuse, _observe
    try:
        from app.rag.config import settings

        if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
            return

        from langfuse import Langfuse, observe

        _langfuse = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
        _observe = observe
        logger.info("Langfuse tracing enabled (host=%s)", settings.LANGFUSE_HOST)
    except ImportError:
        logger.warning("langfuse package not installed — tracing disabled")
    except Exception as exc:
        logger.warning("Langfuse init failed (%s) — tracing disabled", exc)


_init()


def get_langfuse():
    """Return the shared Langfuse client, or None if tracing is disabled."""
    return _langfuse


def sanitize_for_trace(
    value: Any,
    *,
    max_items: int = 20,
    max_text_length: int = 500,
    _depth: int = 0,
) -> Any:
    """Trim large nested payloads so tracing stays informative without exploding."""
    if _depth >= 4:
        return "<max-depth>"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        if len(value) <= max_text_length:
            return value
        return value[:max_text_length] + "...<truncated>"

    if isinstance(value, Mapping):
        items = list(value.items())
        result = {
            str(k): sanitize_for_trace(
                v,
                max_items=max_items,
                max_text_length=max_text_length,
                _depth=_depth + 1,
            )
            for k, v in items[:max_items]
        }
        if len(items) > max_items:
            result["_truncated_items"] = len(items) - max_items
        return result

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        seq = list(value)
        result = [
            sanitize_for_trace(
                item,
                max_items=max_items,
                max_text_length=max_text_length,
                _depth=_depth + 1,
            )
            for item in seq[:max_items]
        ]
        if len(seq) > max_items:
            result.append(f"...<{len(seq) - max_items} more items>")
        return result

    if hasattr(value, "model_dump"):
        try:
            return sanitize_for_trace(
                value.model_dump(mode="json"),
                max_items=max_items,
                max_text_length=max_text_length,
                _depth=_depth + 1,
            )
        except Exception:
            return repr(value)

    if hasattr(value, "__dict__"):
        try:
            return sanitize_for_trace(
                vars(value),
                max_items=max_items,
                max_text_length=max_text_length,
                _depth=_depth + 1,
            )
        except Exception:
            return repr(value)

    return repr(value)


def update_current_observation(**kwargs: Any) -> None:
    """Safely update the active Langfuse observation when tracing is enabled."""
    if _observe is None or _langfuse is None:
        return
    try:
        payload = {k: sanitize_for_trace(v) for k, v in kwargs.items() if v is not None}
        if not payload:
            return

        # Langfuse v4 separates span vs generation updates. We try generation
        # first because it accepts model fields; if there is no active generation,
        # fall back to the current span update.
        try:
            _langfuse.update_current_generation(**payload)
            return
        except Exception:
            pass

        span_payload = {
            k: v
            for k, v in payload.items()
            if k in {"name", "input", "output", "metadata", "version", "level", "status_message"}
        }
        if span_payload:
            _langfuse.update_current_span(**span_payload)
    except Exception:
        pass


def observe(*args, **kwargs):
    """Decorator that wraps a function/coroutine/generator with a Langfuse span.

    Falls back to a no-op decorator when Langfuse is not configured.

    Usage:
        @observe
        async def my_fn(...): ...

        @observe(as_type="generation", name="my_gen")
        async def my_llm_call(...): ...
    """
    if _observe is None:
        # No-op: called as @observe or @observe(...) — handle both forms.
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        # Called with arguments: return a no-op decorator factory.
        def _noop_factory(fn):
            return fn
        return _noop_factory

    return _observe(*args, **kwargs)
