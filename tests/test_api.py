from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.schemas import RunReport, RunStatus


class FakeRunner:
    class Planner:
        name = "fake"

    planner = Planner()

    async def run(self, scenario, run_id=None):
        now = datetime.now(UTC)
        return RunReport(
            run_id=run_id or uuid4(), title=scenario.title,
            objective=scenario.objective, target_url=scenario.target_url,
            status=RunStatus.PASSED, started_at=now, finished_at=now,
            duration_ms=5, steps=[], findings=[], browser_console=[],
            network_events=[], summary="Fake test run passed.", artifacts={},
            planner_provider="fake",
        )


def make_settings(tmp_path: Path, token: str | None = None) -> Settings:
    return Settings(
        database_path=tmp_path / "runs.db",
        artifacts_dir=tmp_path / "artifacts",
        allowed_target_hosts=("qa.example.com",),
        allow_private_targets=False,
        qa_api_token=token,
    )


def test_health_and_create_list_get_run(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    app.state.runner = FakeRunner()
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        created = client.post("/runs", json={
            "title": "Homepage QA", "target_url": "https://qa.example.com",
            "objective": "Verify the homepage heading.",
        })
        assert created.status_code == 201
        run_id = created.json()["run_id"]
        assert client.get(f"/runs/{run_id}").status_code == 200
        assert client.get("/runs").json()[0]["title"] == "Homepage QA"


def test_api_token_is_required_when_configured(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, token="test-secret"))
    app.state.runner = FakeRunner()
    with TestClient(app) as client:
        response = client.post("/runs", json={
            "title": "Homepage QA", "target_url": "https://qa.example.com",
            "objective": "Verify the homepage heading.",
        })
        assert response.status_code == 401
        response = client.post("/runs", headers={"Authorization": "Bearer test-secret"}, json={
            "title": "Homepage QA", "target_url": "https://qa.example.com",
            "objective": "Verify the homepage heading.",
        })
        assert response.status_code == 201


def test_unknown_run_and_artifact_are_404(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        missing = str(uuid4())
        assert client.get(f"/runs/{missing}").status_code == 404
        assert client.get(f"/runs/{missing}/artifacts/trace.zip").status_code == 404


def test_dashboard_and_demo_pages_are_served(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        assert "Browser QA workspace" in client.get("/").text
        assert "Browser QA Demo Store" in client.get("/demo").text
