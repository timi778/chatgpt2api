"""按邮箱 provider/domain 分组统计注册成功率，并支持停用低成功率域名。

某些临时邮箱域名会被 OpenAI 最终风控拒绝（create_account 返回
registration_disallowed），协议修复后仍有部分失败时，按 provider/domain
分组统计可以定位是哪个域名成功率低，停用后成功率可接近 100%。

统计数据存储在 ``data/register_domain_stats.json``，结构：
{
  "<provider>|<domain>": {
    "total": 10,
    "success": 7,
    "fail": 3,
    "last_error": "...",
    "last_updated": "2026-07-08T14:00:00+00:00",
    "disabled": false,
    "disabled_reason": ""
  }
}
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from services.config import DATA_DIR

STATS_FILE = DATA_DIR / "register_domain_stats.json"
_stats_lock = threading.Lock()

# 默认自动停用阈值：至少尝试 N 次且成功率低于该比例时停用
DEFAULT_MIN_ATTEMPTS = 5
DEFAULT_MIN_SUCCESS_RATE = 0.2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict[str, dict[str, Any]]:
    try:
        if STATS_FILE.exists():
            data = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save(store: dict[str, dict[str, Any]]) -> None:
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ordered = {key: store[key] for key in sorted(store)}
    STATS_FILE.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _key(provider: str, domain: str) -> str:
    return f"{str(provider or '').strip()}|{str(domain or '').strip().lower()}"


def extract_domain(email: str) -> str:
    """从邮箱地址提取域名（@ 之后部分，小写）。"""
    parts = str(email or "").strip().rsplit("@", 1)
    return parts[1].strip().lower() if len(parts) == 2 and parts[1].strip() else ""


def record_attempt(provider: str, domain: str, *, success: bool, error: str = "") -> None:
    """记录一次注册尝试的结果。

    按 (provider, domain) 分组累加 total/success/fail，并更新 last_error 和时间戳。
    """
    key = _key(provider, domain)
    if not key or key.endswith("|"):
        return
    with _stats_lock:
        store = _load()
        entry = store.get(key)
        if not isinstance(entry, dict):
            entry = {"total": 0, "success": 0, "fail": 0, "last_error": "", "last_updated": "", "disabled": False, "disabled_reason": ""}
        entry["total"] = int(entry.get("total") or 0) + 1
        if success:
            entry["success"] = int(entry.get("success") or 0) + 1
        else:
            entry["fail"] = int(entry.get("fail") or 0) + 1
        if not success:
            entry["last_error"] = str(error or "")[:500]
        entry["last_updated"] = _now_iso()
        store[key] = entry
        _save(store)


def get_stats() -> dict[str, dict[str, Any]]:
    """返回全部 provider/domain 统计快照。"""
    with _stats_lock:
        return _load()


def get_entry(provider: str, domain: str) -> dict[str, Any] | None:
    """返回某个 (provider, domain) 的统计条目。"""
    with _stats_lock:
        return _load().get(_key(provider, domain))


def get_success_rate(provider: str, domain: str) -> float:
    """返回成功率（0~1），无数据返回 -1。"""
    entry = get_entry(provider, domain)
    if not entry or int(entry.get("total") or 0) == 0:
        return -1.0
    return int(entry.get("success") or 0) / int(entry.get("total") or 1)


def is_domain_disabled(provider: str, domain: str) -> bool:
    """检查某个 (provider, domain) 是否已被停用。"""
    entry = get_entry(provider, domain)
    return bool(entry and entry.get("disabled"))


def disable_domain(provider: str, domain: str, *, reason: str = "") -> None:
    """手动停用某个 (provider, domain)。"""
    key = _key(provider, domain)
    if not key or key.endswith("|"):
        return
    with _stats_lock:
        store = _load()
        entry = store.get(key)
        if not isinstance(entry, dict):
            entry = {"total": 0, "success": 0, "fail": 0, "last_error": "", "last_updated": "", "disabled": False, "disabled_reason": ""}
        entry["disabled"] = True
        entry["disabled_reason"] = str(reason or "manual")[:500]
        entry["last_updated"] = _now_iso()
        store[key] = entry
        _save(store)


def enable_domain(provider: str, domain: str) -> None:
    """重新启用某个已被停用的 (provider, domain)。"""
    key = _key(provider, domain)
    with _stats_lock:
        store = _load()
        entry = store.get(key)
        if isinstance(entry, dict):
            entry["disabled"] = False
            entry["disabled_reason"] = ""
            entry["last_updated"] = _now_iso()
            store[key] = entry
            _save(store)


def auto_disable_low_success(
    min_attempts: int = DEFAULT_MIN_ATTEMPTS,
    min_success_rate: float = DEFAULT_MIN_SUCCESS_RATE,
) -> list[str]:
    """自动停用成功率低于阈值的域名。

    仅当 total >= min_attempts 且 success/total < min_success_rate 时停用。
    返回被停用的 key 列表（``provider|domain``）。
    """
    disabled_keys: list[str] = []
    with _stats_lock:
        store = _load()
        for key, entry in store.items():
            if not isinstance(entry, dict) or entry.get("disabled"):
                continue
            total = int(entry.get("total") or 0)
            if total < min_attempts:
                continue
            rate = int(entry.get("success") or 0) / total
            if rate < min_success_rate:
                entry["disabled"] = True
                entry["disabled_reason"] = f"auto_disabled: rate={rate:.0%} (<{min_success_rate:.0%}, n={total})"
                entry["last_updated"] = _now_iso()
                store[key] = entry
                disabled_keys.append(key)
        if disabled_keys:
            _save(store)
    return disabled_keys


def get_disabled_domains() -> list[dict[str, Any]]:
    """返回所有被停用的 (provider, domain) 列表。"""
    with _stats_lock:
        store = _load()
    result: list[dict[str, Any]] = []
    for key, entry in store.items():
        if isinstance(entry, dict) and entry.get("disabled"):
            provider, _, domain = key.partition("|")
            result.append({
                "provider": provider,
                "domain": domain,
                "total": int(entry.get("total") or 0),
                "success": int(entry.get("success") or 0),
                "fail": int(entry.get("fail") or 0),
                "disabled_reason": str(entry.get("disabled_reason") or ""),
                "last_updated": str(entry.get("last_updated") or ""),
            })
    return result
