from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.support import require_admin
from services.register_service import register_service


class RegisterConfigRequest(BaseModel):
    mail: dict | None = None
    proxy: str | None = None
    total: int | None = None
    threads: int | None = None
    mode: str | None = None
    target_quota: int | None = None
    target_available: int | None = None
    check_interval: int | None = None


class OutlookPoolResetRequest(BaseModel):
    scope: str | None = None


class DomainStatsActionRequest(BaseModel):
    provider: str = ""
    domain: str = ""


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/register")
    async def get_register_config(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.get()}

    @router.post("/api/register")
    async def update_register_config(body: RegisterConfigRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.update(body.model_dump(exclude_none=True))}

    @router.post("/api/register/start")
    async def start_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.start()}

    @router.post("/api/register/stop")
    async def stop_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.stop()}

    @router.post("/api/register/reset")
    async def reset_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset()}

    @router.post("/api/register/outlook-pool/reset")
    async def reset_outlook_pool(body: OutlookPoolResetRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset_outlook_pool(body.scope or "all")}

    @router.get("/api/register/domain-stats")
    async def get_domain_stats(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.register import domain_stats
        stats = domain_stats.get_stats()
        entries = []
        for key, entry in stats.items():
            provider, _, domain = key.partition("|")
            total = int(entry.get("total") or 0)
            success = int(entry.get("success") or 0)
            entries.append({
                "provider": provider,
                "domain": domain,
                "total": total,
                "success": success,
                "fail": int(entry.get("fail") or 0),
                "success_rate": round(success / total, 4) if total else -1,
                "disabled": bool(entry.get("disabled")),
                "disabled_reason": str(entry.get("disabled_reason") or ""),
                "last_error": str(entry.get("last_error") or ""),
                "last_updated": str(entry.get("last_updated") or ""),
            })
        entries.sort(key=lambda x: (x["disabled"], x["success_rate"] if x["success_rate"] >= 0 else 1))
        return {"stats": entries}

    @router.post("/api/register/domain-stats/disable")
    async def disable_domain(body: DomainStatsActionRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.register import domain_stats
        domain_stats.disable_domain(body.provider, body.domain, reason="manual")
        return {"ok": True}

    @router.post("/api/register/domain-stats/enable")
    async def enable_domain(body: DomainStatsActionRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.register import domain_stats
        domain_stats.enable_domain(body.provider, body.domain)
        return {"ok": True}

    @router.post("/api/register/domain-stats/auto-disable")
    async def auto_disable_domains(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.register import domain_stats
        disabled = domain_stats.auto_disable_low_success()
        return {"disabled": disabled}

    @router.get("/api/register/events")
    async def register_events(token: str = ""):
        require_admin(f"Bearer {token}")

        async def stream():
            last = ""
            while True:
                payload = json.dumps(register_service.get(), ensure_ascii=False)
                if payload != last:
                    last = payload
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
