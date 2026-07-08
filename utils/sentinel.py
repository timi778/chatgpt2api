"""OpenAI Sentinel Token (PoW) 生成与请求工具函数。

用于密码登录、注册等需要 sentinel token 的流程。

关键概念：
- OpenAI-Sentinel-Token: 标准 sentinel 令牌，JSON 结构 {p, t, c, id, flow}，
  其中 p 是 proof-of-work 解，c 是服务端下发的 challenge token。
- OpenAI-Sentinel-SO-Token: 独立的 SO(Signature Observer) 令牌，来源是
  Sentinel /req 返回的 ``so`` 字段。生成方式和 proof-of-work 类似
  （同样使用 FNV-1a 哈希 + seed/difficulty），也可能以 turnstile dx 指令形式出现。
  官方前端在采集 SO 信号时会等待约 5000ms 的 observer 时间。
"""
from __future__ import annotations

import base64
import json
import logging
import random
import time
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from curl_cffi.requests import Session

logger = logging.getLogger(__name__)

# 官方 Sentinel SDK 版本标识（对应 sdk.js 路径中的构建号）
SENTINEL_SDK_VERSION = "20260124ceb8"
SENTINEL_SDK_URL = f"https://sentinel.openai.com/sentinel/{SENTINEL_SDK_VERSION}/sdk.js"
# SO token 采集/observer 等待时间（毫秒），按官方前端逻辑使用 5000ms
SENTINEL_SO_OBSERVER_MS = 5000


class SentinelTokenGenerator:
    """Sentinel Token 生成器（PoW - Proof of Work）。"""
    MAX_ATTEMPTS = 500_000
    ERROR_PREFIX = "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D"

    def __init__(self, device_id: str, ua: str):
        self.device_id = device_id
        self.user_agent = ua
        self.sid = str(uuid.uuid4())

    @staticmethod
    def _fnv1a_32(text: str) -> str:
        h = 2166136261
        for ch in text:
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
        h ^= h >> 16
        h = (h * 2246822507) & 0xFFFFFFFF
        h ^= h >> 13
        h = (h * 3266489909) & 0xFFFFFFFF
        h ^= h >> 16
        return format(h & 0xFFFFFFFF, "08x")

    def _get_config(self) -> list:
        perf_now = random.uniform(1000, 50000)
        return [
            "1920x1080",
            time.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)", time.gmtime()),
            4294705152,
            random.random(),
            self.user_agent,
            SENTINEL_SDK_URL,
            None,
            None,
            "en-US",
            random.random(),
            random.choice(["vendorSub-undefined", "plugins-undefined", "mimeTypes-undefined", "hardwareConcurrency-undefined"]),
            random.choice(["location", "implementation", "URL", "documentURI", "compatMode"]),
            random.choice(["Object", "Function", "Array", "Number", "parseFloat", "undefined"]),
            perf_now,
            self.sid,
            "",
            random.choice([4, 8, 12, 16]),
            time.time() * 1000 - perf_now,
        ]

    @staticmethod
    def _b64(data) -> str:
        return base64.b64encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).decode("ascii")

    def generate_requirements_token(self) -> str:
        data = self._get_config()
        data[3] = 1
        data[9] = round(random.uniform(5, 50))
        return "gAAAAAC" + self._b64(data)

    def generate_token(self, seed: str, difficulty: str) -> str:
        start = time.time()
        data = self._get_config()
        difficulty = str(difficulty or "0")
        for i in range(self.MAX_ATTEMPTS):
            data[3] = i
            data[9] = round((time.time() - start) * 1000)
            payload = self._b64(data)
            if self._fnv1a_32(seed + payload)[: len(difficulty)] <= difficulty:
                return "gAAAAAB" + payload + "~S"
        return "gAAAAAB" + self.ERROR_PREFIX + self._b64(str(None))


# ── 默认 User-Agent 和 sec-ch-ua ──────────────────────────────
DEFAULT_SENTINEL_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
DEFAULT_SENTINEL_SEC_CH_UA = '"Chromium";v="145", "Google Chrome";v="145", "Not/A)Brand";v="99"'


def build_sentinel_token(
    session: "Session",
    device_id: str,
    flow: str,
    *,
    user_agent: str = "",
    sec_ch_ua: str = "",
) -> tuple[str, str]:
    """请求 sentinel token 并返回 (sentinel_header_value, oai_sc_cookie_value)。

    Args:
        session: curl_cffi Session 实例
        device_id: 设备 ID
        flow: 流程标识（如 "password_verify", "username_password_create" 等）
        user_agent: 可选的 User-Agent 覆盖
        sec_ch_ua: 可选的 sec-ch-ua 覆盖

    Returns:
        (openai-sentinel-token header value, oai-sc cookie value) 元组

    Raises:
        RuntimeError: sentinel 请求失败
    """
    ua = user_agent or DEFAULT_SENTINEL_USER_AGENT
    ch_ua = sec_ch_ua or DEFAULT_SENTINEL_SEC_CH_UA
    generator = SentinelTokenGenerator(device_id, ua)
    resp = session.post(
        "https://sentinel.openai.com/backend-api/sentinel/req",
        data=json.dumps({"p": generator.generate_requirements_token(), "id": device_id, "flow": flow}),
        headers={
            "Content-Type": "text/plain;charset=UTF-8",
            "Referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html",
            "Origin": "https://sentinel.openai.com",
            "User-Agent": ua,
            "sec-ch-ua": ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
        timeout=20,
        verify=False,
    )

    try:
        data = resp.json() if resp.text else {}
    except Exception:
        fallback = json.dumps(
            {"p": generator.generate_requirements_token(), "t": "", "c": "", "id": device_id, "flow": flow},
            separators=(",", ":"),
        )
        return fallback, ""

    token = str(data.get("token") or "").strip()
    if resp.status_code != 200 or not token:
        raise RuntimeError(f"sentinel_req_failed_{resp.status_code}")
    pow_data = data.get("proofofwork") or {}
    p_value = (
        generator.generate_token(str(pow_data.get("seed") or ""), str(pow_data.get("difficulty") or "0"))
        if pow_data.get("required") and pow_data.get("seed")
        else generator.generate_requirements_token()
    )
    sentinel_value = json.dumps({"p": p_value, "t": "", "c": token, "id": device_id, "flow": flow}, separators=(",", ":"))
    # oai-sc cookie = "0" + sentinel token "c" value (the challenge token from the server)
    oai_sc_value = "0" + token
    return sentinel_value, oai_sc_value


def _request_sentinel_req(
    session: "Session",
    device_id: str,
    flow: str,
    requirements_token: str,
    ua: str,
    ch_ua: str,
) -> dict:
    """向 Sentinel /req 发送请求并返回解析后的 JSON。

    flow 决定了服务端下发的 challenge 类型（proofofwork / so / turnstile）。
    requirements_token 由调用方预先生成，同时用于请求体和后续 turnstile dx 的 XOR 密钥。
    """
    resp = session.post(
        "https://sentinel.openai.com/backend-api/sentinel/req",
        data=json.dumps({"p": requirements_token, "id": device_id, "flow": flow}),
        headers={
            "Content-Type": "text/plain;charset=UTF-8",
            "Referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html",
            "Origin": "https://sentinel.openai.com",
            "User-Agent": ua,
            "sec-ch-ua": ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
        timeout=20,
        verify=False,
    )
    try:
        return resp.json() if resp.text else {}
    except Exception:
        return {}


def _generate_so_token(
    so_data,
    generator: "SentinelTokenGenerator",
    requirements_token: str,
) -> str:
    """根据 Sentinel /req 返回的 ``so`` 字段生成 SO token。

    生成方式和 proof-of-work 类似：
    - 若 so 含 seed/difficulty → 用 FNV-1a PoW 解出 gAAAAAB…~S
    - 若 so 含 dx → 用 turnstile VM 解指令
    - 否则返回空串（服务端未要求 SO）
    """
    if not isinstance(so_data, dict):
        return ""
    if so_data.get("required") and so_data.get("seed"):
        return generator.generate_token(
            str(so_data.get("seed") or ""),
            str(so_data.get("difficulty") or "0"),
        )
    dx = so_data.get("dx")
    if dx:
        try:
            from utils.turnstile import solve_turnstile_token

            solved = solve_turnstile_token(str(dx), requirements_token)
            return str(solved or "")
        except Exception as exc:
            logger.warning("sentinel so turnstile solve failed: %s", exc)
            return ""
    return ""


def build_sentinel_tokens(
    session: "Session",
    device_id: str,
    flow: str,
    *,
    user_agent: str = "",
    sec_ch_ua: str = "",
    observer_ms: int = SENTINEL_SO_OBSERVER_MS,
) -> tuple[str, str]:
    """请求 Sentinel /req 并同时生成 Sentinel token 和 SO token。

    对齐浏览器真实注册流程的 create_account 阶段：
    1. 先请求 Sentinel req，flow 使用 oauth_create_account（由调用方传入）。
    2. 从返回的 requirements 生成 Sentinel token（proofofwork 解）。
    3. 从返回的 ``so`` 字段生成 SO token（生成方式与 PoW 类似）。
    4. SO token 采集/observer 等待 observer_ms（默认 5000ms）。

    Args:
        session: curl_cffi Session 实例
        device_id: 设备 ID
        flow: 流程标识（create_account 阶段使用 "oauth_create_account"）
        user_agent: 可选的 User-Agent 覆盖
        sec_ch_ua: 可选的 sec-ch-ua 覆盖
        observer_ms: SO token observer 等待毫秒数，默认 5000

    Returns:
        (openai-sentinel-token header value, openai-sentinel-so-token header value)
        so-token 可能为空串（服务端未下发 so requirements 时）。

    Raises:
        RuntimeError: sentinel 请求失败
    """
    ua = user_agent or DEFAULT_SENTINEL_USER_AGENT
    ch_ua = sec_ch_ua or DEFAULT_SENTINEL_SEC_CH_UA
    generator = SentinelTokenGenerator(device_id, ua)

    # 预生成 requirements token，同时用于 /req 请求体和后续 turnstile dx 的 XOR 密钥
    requirements_token = generator.generate_requirements_token()

    # Step 7: create_account 前先请求 Sentinel req
    data = _request_sentinel_req(session, device_id, flow, requirements_token, ua, ch_ua)
    token = str(data.get("token") or "").strip()
    if not token:
        raise RuntimeError(f"sentinel_req_failed_no_token flow={flow}")

    # Step 8: 从 requirements 生成 Sentinel token（proofofwork 解）
    pow_data = data.get("proofofwork") or {}
    if pow_data.get("required") and pow_data.get("seed"):
        p_value = generator.generate_token(
            str(pow_data.get("seed") or ""),
            str(pow_data.get("difficulty") or "0"),
        )
    else:
        p_value = requirements_token

    sentinel_value = json.dumps(
        {"p": p_value, "t": "", "c": token, "id": device_id, "flow": flow},
        separators=(",", ":"),
    )

    # Step 8 (cont): 从 so requirements 生成 so-token
    # SO token 的采集/observer 等待时间按官方前端逻辑使用 5000ms
    # 注意：turnstile dx 的 XOR 密钥用的是 requirements_token（gAAAAAC 前缀），
    # 不是 PoW 解（gAAAAAB 前缀），和官方 SDK vt[16] 存储的逻辑一致
    so_token = ""
    so_data = data.get("so")
    if so_data is not None:
        if observer_ms > 0:
            time.sleep(observer_ms / 1000.0)
        so_token = _generate_so_token(so_data, generator, requirements_token)

    # 日志：记录 token 长度、SDK 版本、so-token 是否生成，不打印明文
    logger.info(
        "sentinel sdk=%s flow=%s token_len=%d so_token=%s so_len=%d",
        SENTINEL_SDK_VERSION,
        flow,
        len(sentinel_value),
        "yes" if so_token else "no",
        len(so_token),
    )

    return sentinel_value, so_token
