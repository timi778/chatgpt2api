from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from services.config import config
from services.protocol.conversation import ImageGenerationError
from services.protocol.error_response import openai_error_payload


class AsyncImageResultError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or openai_error_payload(message, status_code)


def is_image_response_missing(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    data = result.get("data")
    if isinstance(data, list):
        return not data
    output = result.get("output")
    if isinstance(output, list):
        return not any(
            isinstance(item, dict)
            and str(item.get("type") or "") == "image_generation_call"
            and str(item.get("result") or "").strip()
            for item in output
        )
    choices = result.get("choices")
    if isinstance(choices, list):
        return not any(_choice_has_image(choice) for choice in choices if isinstance(choice, dict))
    return False


def _choice_has_image(choice: dict[str, Any]) -> bool:
    message = choice.get("message")
    if not isinstance(message, dict):
        return False
    content = str(message.get("content") or "")
    return "data:image/" in content or "![" in content or "/images/" in content


def ensure_image_result(result: dict[str, Any]) -> dict[str, Any]:
    if is_image_response_missing(result):
        message = image_missing_message(result)
        raise AsyncImageResultError(message, 502)
    return result


def image_missing_message(result: dict[str, Any]) -> str:
    message = str(result.get("message") or "").strip()
    if message:
        return message
    choices = result.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            item = choice.get("message")
            if isinstance(item, dict) and str(item.get("content") or "").strip():
                return str(item.get("content") or "").strip()
    return "image generation failed: upstream returned no image"


def image_error_payload(exc: Exception) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, AsyncImageResultError):
        return exc.status_code, exc.payload
    if isinstance(exc, ImageGenerationError):
        return int(exc.status_code), exc.to_openai_error()
    if isinstance(exc, HTTPException):
        status_code = int(exc.status_code or 500)
        return status_code, openai_error_payload(exc.detail, status_code)
    return 502, openai_error_payload(str(exc) or "image generation failed", 502)


def async_json_heartbeat_response(
    run: Callable[[], dict[str, Any]],
    *,
    timeout_secs: float | None = None,
    heartbeat_secs: float | None = None,
    first_wait_secs: float = 1.0,
) -> JSONResponse | StreamingResponse:
    timeout = float(timeout_secs or config.image_poll_timeout_secs or 360)
    heartbeat = float(heartbeat_secs or config.image_response_heartbeat_secs or 5.0)
    items: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)
    started = time.monotonic()

    def _worker() -> None:
        try:
            items.put(("result", ensure_image_result(run())))
        except Exception as exc:
            items.put(("error", exc))

    threading.Thread(target=_worker, daemon=True, name="image-json-response").start()

    try:
        kind, payload = items.get(timeout=max(0.0, min(first_wait_secs, timeout)))
    except queue.Empty:
        kind = ""
        payload = None

    if kind == "result":
        return JSONResponse(content=payload)
    if kind == "error":
        exc = payload if isinstance(payload, Exception) else RuntimeError(str(payload))
        return error_json_response(exc)

    def _body() -> Iterator[bytes]:
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                status_code, payload = image_error_payload(
                    AsyncImageResultError(f"image generation timed out after {int(timeout)} seconds", 504)
                )
                yield json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                return
            try:
                kind, payload = items.get(timeout=min(heartbeat, remaining))
            except queue.Empty:
                yield b" \n"
                continue
            if kind == "result":
                yield json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                return
            exc = payload if isinstance(payload, Exception) else RuntimeError(str(payload))
            _, error_payload = image_error_payload(exc)
            yield json.dumps(error_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            return

    return StreamingResponse(
        _body(),
        media_type="application/json",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def error_json_response(exc: Exception) -> JSONResponse:
    status_code, payload = image_error_payload(exc)
    return JSONResponse(status_code=status_code, content=payload)
