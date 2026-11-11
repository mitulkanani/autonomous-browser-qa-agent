from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import Settings, settings
from app.services.browser_runner import BrowserQARunner
from app.services.storage import RunStore

WEB_DIR = Path(__file__).parent / "web"


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    app_settings = custom_settings or settings
    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        description=(
            "A safety-first browser QA agent with an allowlisted target policy, "
            "constrained actions, screenshots, traces, and structured findings."
        ),
    )
    app.state.settings = app_settings
    app.state.store = RunStore(app_settings.database_path)
    app.state.runner = BrowserQARunner(app_settings)
    app.state.run_semaphore = asyncio.Semaphore(max(1, app_settings.max_concurrent_runs))
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/demo", include_in_schema=False)
    async def demo_site() -> FileResponse:
        return FileResponse(WEB_DIR / "demo.html")

    return app


app = create_app()
