from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from playwright.async_api import Page
from playwright.sync_api import sync_playwright

from app.core.config import Settings
from app.models.schemas import AgentStep, LocatorSpec, RunStatus, ScenarioRequest, StepStatus
from app.services.browser_runner import BrowserQARunner


@pytest.fixture
def local_target() -> str:
    return "http://127.0.0.1:8000/"


def make_runner(tmp_path: Path) -> BrowserQARunner:
    executable = shutil.which("chromium") or shutil.which("google-chrome")
    if not executable:
        with sync_playwright() as playwright:
            candidate = Path(playwright.chromium.executable_path)
            executable = str(candidate) if candidate.exists() else None
    if not executable:
        pytest.skip("Install the Playwright Chromium browser to run browser integration tests.")
    cfg = Settings(
        database_path=tmp_path / "runs.db",
        artifacts_dir=tmp_path / "artifacts",
        allowed_target_hosts=("127.0.0.1",),
        allow_private_targets=False,
        allow_loopback_targets=True,
        browser_executable_path=executable,
        browser_headless=True,
        action_timeout_ms=4000,
        navigation_timeout_ms=8000,
        max_run_seconds=30,
        max_concurrent_runs=1,
        planner_provider="mock",
    )
    return BrowserQARunner(cfg)


@pytest.mark.asyncio
async def test_real_browser_run_captures_screenshot_and_trace(tmp_path: Path, local_target: str, monkeypatch) -> None:
    async def fake_goto(page: Page, _url: str, **_kwargs):
        await page.set_content("""<!doctype html><html><head><title>QA Integration Fixture</title></head>
        <body><h1>Integration Test Page</h1><button type='button'>Safe action</button>
        <button type='submit'>Submit Form</button><input type='password' aria-label='Password'></body></html>""")
        return None

    monkeypatch.setattr(Page, "goto", fake_goto)
    runner = make_runner(tmp_path)
    scenario = ScenarioRequest(
        title="Browser integration test", target_url=local_target,
        objective="Verify the test page loads and has a heading.",
        expected_title="QA Integration Fixture", max_steps=6,
    )
    report = await runner.run(scenario)
    assert report.status == RunStatus.PASSED
    assert len(report.steps) == 3
    assert all(step.status == StepStatus.PASSED for step in report.steps)
    assert "screenshot" in report.artifacts
    assert "trace" in report.artifacts


@pytest.mark.asyncio
async def test_agent_blocks_submit_button_click(tmp_path: Path, local_target: str, monkeypatch) -> None:
    async def fake_goto(page: Page, _url: str, **_kwargs):
        await page.set_content("""<!doctype html><html><head><title>QA Integration Fixture</title></head>
        <body><h1>Integration Test Page</h1><button type='submit'>Submit Form</button></body></html>""")
        return None

    monkeypatch.setattr(Page, "goto", fake_goto)
    runner = make_runner(tmp_path)
    scenario = ScenarioRequest(
        title="Submit safety test", target_url=local_target,
        objective="Prove that submit buttons are blocked.", max_steps=1,
        steps=[AgentStep(
            action="click",
            locator=LocatorSpec(strategy="role", value="Submit Form", role="button"),
        )],
    )
    report = await runner.run(scenario)
    assert report.status == RunStatus.BLOCKED
    assert report.steps[0].status == StepStatus.BLOCKED
    assert any(f.category == "security_policy" for f in report.findings)


@pytest.mark.asyncio
async def test_agent_blocks_sensitive_text_field_fill(tmp_path: Path, local_target: str, monkeypatch) -> None:
    async def fake_goto(page: Page, _url: str, **_kwargs):
        await page.set_content("""<!doctype html><html><head><title>QA Integration Fixture</title></head>
        <body><h1>Integration Test Page</h1><label for='cust'>Customer email</label>
        <input id='cust' name='customer_email' type='text'></body></html>""")
        return None

    monkeypatch.setattr(Page, "goto", fake_goto)
    runner = make_runner(tmp_path)
    scenario = ScenarioRequest(
        title="Sensitive input test", target_url=local_target,
        objective="Ensure personal fields cannot be filled automatically.", max_steps=1,
        steps=[AgentStep(
            action="fill",
            locator=LocatorSpec(strategy="label", value="Customer email"),
            value="person@example.com",
        )],
    )
    report = await runner.run(scenario)
    assert report.status == RunStatus.BLOCKED
    assert report.steps[0].status == StepStatus.BLOCKED


@pytest.mark.asyncio
async def test_agent_allows_non_sensitive_search_fill_and_safe_click(tmp_path: Path, local_target: str, monkeypatch) -> None:
    async def fake_goto(page: Page, _url: str, **_kwargs):
        await page.set_content("""<!doctype html><html><head><title>QA Integration Fixture</title></head>
        <body><h1>Integration Test Page</h1><input id='search' type='search' placeholder='Search products'>
        <button type='button' aria-label='Search'>Search</button></body></html>""")

    monkeypatch.setattr(Page, "goto", fake_goto)
    runner = make_runner(tmp_path)
    scenario = ScenarioRequest(
        title="Safe search interaction", target_url=local_target,
        objective="Verify the search field can be used without submitting a form.", max_steps=2,
        steps=[
            AgentStep(action="fill", locator=LocatorSpec(strategy="placeholder", value="Search products"), value="keyboard"),
            AgentStep(action="click", locator=LocatorSpec(strategy="role", value="Search", role="button")),
        ],
    )
    report = await runner.run(scenario)
    assert report.status == RunStatus.PASSED
    assert all(step.status == StepStatus.PASSED for step in report.steps)


@pytest.mark.asyncio
async def test_agent_blocks_default_submit_button_and_login_actions(
    tmp_path: Path, local_target: str, monkeypatch
) -> None:
    async def fake_goto(page: Page, _url: str, **_kwargs):
        await page.set_content("""<!doctype html><html><head><title>Safety Fixture</title></head>
        <body><h1>Safety Fixture</h1><button>Continue</button><button type='button'>Sign in</button></body></html>""")
        return None

    monkeypatch.setattr(Page, "goto", fake_goto)
    runner = make_runner(tmp_path)
    scenarios = [
        AgentStep(action="click", locator=LocatorSpec(strategy="role", value="Continue", role="button")),
        AgentStep(action="click", locator=LocatorSpec(strategy="role", value="Sign in", role="button")),
    ]
    for step in scenarios:
        report = await runner.run(ScenarioRequest(
            title="Consequential action safety", target_url=local_target,
            objective="Ensure consequential actions are not clicked.", max_steps=1,
            steps=[step],
        ))
        assert report.status == RunStatus.BLOCKED
        assert report.steps[0].status == StepStatus.BLOCKED
