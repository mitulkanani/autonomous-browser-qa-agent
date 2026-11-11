from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.models.schemas import RunCreated, RunReport, RunSummary, ScenarioRequest
from app.services.browser_runner import BrowserQARunner
from app.services.storage import RunStore

router = APIRouter()


async def require_api_access(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    token = request.app.state.settings.qa_api_token
    if not token:
        return
    expected = f"Bearer {token}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing bearer token.")


@router.get("/health", tags=["meta"])
async def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "planner": request.app.state.runner.planner.name}


@router.post("/runs", response_model=RunCreated, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_access)], tags=["runs"])
async def create_run(payload: ScenarioRequest, request: Request) -> RunCreated:
    semaphore = request.app.state.run_semaphore
    async with semaphore:
        run_id = uuid4()
        report: RunReport = await request.app.state.runner.run(payload, run_id=run_id)
        request.app.state.store.save(report)
    return RunCreated(
        run_id=report.run_id,
        status=report.status,
        summary=report.summary,
        report_url=f"/runs/{report.run_id}",
    )


@router.get("/runs", response_model=list[RunSummary], dependencies=[Depends(require_api_access)], tags=["runs"])
async def list_runs(request: Request, limit: int = 20) -> list[RunSummary]:
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    return request.app.state.store.list(limit=limit)


@router.get("/runs/{run_id}", response_model=RunReport, dependencies=[Depends(require_api_access)], tags=["runs"])
async def get_run(run_id: UUID, request: Request) -> RunReport:
    report = request.app.state.store.get(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="QA run not found.")
    return report


@router.get("/runs/{run_id}/artifacts/{artifact_name}", dependencies=[Depends(require_api_access)], tags=["artifacts"])
async def get_artifact(run_id: UUID, artifact_name: str, request: Request) -> FileResponse:
    if artifact_name not in {"screenshot.png", "trace.zip"}:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    report = request.app.state.store.get(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="QA run not found.")
    required_key = "screenshot" if artifact_name == "screenshot.png" else "trace"
    if required_key not in report.artifacts:
        raise HTTPException(status_code=404, detail="Artifact not available for this run.")
    path = request.app.state.settings.artifacts_dir / str(run_id) / artifact_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found.")
    media_type = "image/png" if artifact_name.endswith(".png") else "application/zip"
    return FileResponse(path, media_type=media_type, filename=artifact_name)
