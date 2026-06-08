from __future__ import annotations

import os
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class _FakeConfig:
    refresh_account_interval_minute = 60


class _FakeAccountService:
    def __init__(self, stop_event: threading.Event):
        self.stop_event = stop_event
        self.refresh_calls: list[tuple[list[str], bool]] = []
        self.keepalive_calls: list[list[str]] = []

    def list_tokens(self) -> list[str]:
        return ["normal-token", "limited-token", "abnormal-token"]

    def list_refresh_token_keepalive_tokens(self) -> list[str]:
        return []

    def refresh_accounts(
        self,
        tokens: list[str],
        progress_id: str | None = None,
        defer_invalid_removal: bool = True,
    ) -> dict:
        self.refresh_calls.append((tokens, defer_invalid_removal))
        self.stop_event.set()
        return {"refreshed": len(tokens), "errors": []}

    def keepalive_refresh_tokens(self, tokens: list[str]) -> dict:
        self.keepalive_calls.append(tokens)
        return {"refreshed": len(tokens), "errors": []}


class AccountWatcherTests(unittest.TestCase):
    def test_account_watcher_refreshes_full_pool_like_manual_refresh(self) -> None:
        from api import support

        stop_event = threading.Event()
        fake_service = _FakeAccountService(stop_event)

        with (
            patch.object(support, "account_service", fake_service),
            patch.object(support, "config", _FakeConfig()),
        ):
            thread = support.start_limited_account_watcher(stop_event)
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(
            fake_service.refresh_calls,
            [(["normal-token", "limited-token", "abnormal-token"], False)],
        )


if __name__ == "__main__":
    unittest.main()
