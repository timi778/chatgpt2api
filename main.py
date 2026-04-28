from __future__ import annotations

import uvicorn
from api import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        app,
        access_log=False,
        log_level="info",
        limit_concurrency=8,
        timeout_keep_alive=30,
    )
