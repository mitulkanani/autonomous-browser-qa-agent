from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from playwright.async_api import Browser, BrowserContext, Error as PlaywrightError, Page, async_playwright

from app.core.config import Settings
from app.models.schemas import (
    AgentStep,
    Finding,
    RunReport,
    RunStatus,
    ScenarioRequest,
    StepRecord,
    StepStatus,
)
from app.services.planner import get_planner
from app.services.url_guard import URLPolicyError, redact_sensitive_text, redact_sensitive_url, validate_target_url

BLOCKED_ACTION_TERMS = re.compile(
    r"\b(pay(?:ment)?|purchase|buy now|checkout|delete|remove|submit|confirm|send|transfer|"
    r"publish|place order|cancel subscription|save|update|create|approve|register|subscribe|"
    r"book|reserve|add to cart|add item|accept|sign out|log out|log in|sign in|login|"
    r"authenticate|continue to payment)\b",
    re.IGNORECASE,
)


class BrowserExecutionError(RuntimeError):
    pass


class BrowserPolicyError(BrowserExecutionError):
    """An otherwise valid browser action was refused by a safety rule."""


def _now() -> datetime:
    return datetime.now(UTC)


class BrowserQARunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.planner = get_planner(settings)
        self.settings.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def _safe_url(self, url: str | None) -> str | None:
        return redact_sensitive_url(url) if url else None

    def _validate_url(self, url: str) -> str:
        return validate_target_url(
            url,
            allowed_hosts=self.settings.allowed_target_hosts,
            allow_private_targets=self.settings.allow_private_targets,
            allow_loopback_targets=self.settings.allow_loopback_targets,
        )

    async def _snapshot(self, page: Page) -> dict[str, Any]:
        try:
            body_text = await page.locator("body").inner_text(timeout=1500)
        except PlaywrightError:
            body_text = ""
        body_text = redact_sensitive_text(body_text, limit=4500)
        try:
            controls = await page.locator(
                "a,button,input,textarea,select,[role='button']"
            ).evaluate_all(
                """elements => elements.slice(0, 80).map(el => ({
                    tag: el.tagName.toLowerCase(),
                    role: el.getAttribute('role') || '',
                    type: el.getAttribute('type') || '',
                    name: (el.getAttribute('aria-label') || el.innerText || el.getAttribute('title') || '').trim().slice(0, 120),
                    placeholder: (el.getAttribute('placeholder') || '').slice(0, 120),
                    href: el.tagName.toLowerCase() === 'a' ? el.href : '',
                    disabled: Boolean(el.disabled)
                }))"""
            )
        except PlaywrightError:
            controls = []
        for control in controls:
            control["name"] = redact_sensitive_text(str(control.get("name", "")), 120)
            control["placeholder"] = redact_sensitive_text(str(control.get("placeholder", "")), 120)
            if control.get("href"):
                control["href"] = self._safe_url(str(control["href"]))
        return {
            "url": self._safe_url(page.url),
            "title": redact_sensitive_text(await page.title(), 300),
            "visible_text": body_text,
            "interactive_elements": controls,
        }

    def _locator(self, page: Page, spec: Any):
        if spec.strategy == "role":
            return page.get_by_role(spec.role, name=spec.value, exact=spec.exact)
        if spec.strategy == "text":
            return page.get_by_text(spec.value, exact=spec.exact)
        if spec.strategy == "label":
            return page.get_by_label(spec.value, exact=spec.exact)
        if spec.strategy == "placeholder":
            return page.get_by_placeholder(spec.value, exact=spec.exact)
        if spec.strategy == "test_id":
            return page.get_by_test_id(spec.value)
        if spec.strategy == "css":
            return page.locator(spec.value)
        raise BrowserExecutionError("Unsupported locator strategy.")

    async def _single_locator(self, page: Page, spec: Any):
        locator = self._locator(page, spec)
        count = await locator.count()
        if count != 1:
            raise BrowserExecutionError(
                f"Locator matched {count} elements; exactly one match is required."
            )
        return locator

    async def _execute_action(
        self,
        page: Page,
        step: AgentStep,
        screenshot_path: Path,
    ) -> tuple[str, str | None]:
        """Execute one constrained action. No evaluate/JS/code actions are exposed."""
        if step.action == "finish":
            return "Agent finished the scenario.", None

        if step.action == "assert_title":
            actual = await page.title()
            if step.expected and step.expected.casefold() not in actual.casefold():
                raise BrowserExecutionError(
                    f"Expected title to contain '{step.expected}', got '{actual}'."
                )
            return f"Verified page title: {actual}", None

        if step.action == "screenshot":
            await self._prepare_screenshot(page)
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot_path), full_page=True, animations="disabled")
            return "Captured full-page screenshot.", str(screenshot_path)

        if step.locator is None:
            raise BrowserExecutionError(f"Action '{step.action}' requires a locator.")
        locator = await self._single_locator(page, step.locator)
        await locator.wait_for(state="visible", timeout=self.settings.action_timeout_ms)

        if step.action == "assert_visible":
            return f"Element is visible: {step.locator.strategy}={step.locator.value}", None

        if step.action == "assert_text":
            actual = await locator.inner_text(timeout=self.settings.action_timeout_ms)
            if step.expected and step.expected.casefold() not in actual.casefold():
                raise BrowserExecutionError(
                    f"Expected text '{step.expected}' was not found in the selected element."
                )
            return "Verified expected text is present.", None

        if step.action == "fill":
            element_type = (await locator.get_attribute("type") or "").lower()
            if element_type in {"password", "file", "hidden"}:
                raise BrowserPolicyError(f"Filling input type '{element_type}' is prohibited.")
            if element_type in {"email", "tel", "number", "date", "datetime-local"}:
                raise BrowserPolicyError(
                    f"Filling potentially sensitive or transactional input type '{element_type}' is prohibited."
                )
            field_metadata = " ".join([
                await locator.get_attribute("name") or "",
                await locator.get_attribute("id") or "",
                await locator.get_attribute("autocomplete") or "",
                await locator.get_attribute("aria-label") or "",
                await locator.get_attribute("placeholder") or "",
            ]).casefold()
            if re.search(
                r"password|e-mail|email|phone|telephone|credit.?card|card.?number|cvv|cvc|"
                r"ssn|social.?security|routing|account.?number|api.?key|secret|token|address|"
                r"first.?name|last.?name|full.?name|user.?name|date.?of.?birth|birth.?date|"
                r"\bdob\b|postal|\bzip\b|passport|driver.?license|tax.?id|\bvat\b|"
                r"\biban\b|\bbank\b|recipient|contact.?person",
                field_metadata,
            ):
                raise BrowserPolicyError("Filling an input with sensitive-field metadata is prohibited.")
            await locator.fill(step.value or "", timeout=self.settings.action_timeout_ms)
            return "Filled a non-sensitive field; the value is intentionally not recorded.", None

        if step.action == "click":
            details = await locator.evaluate(
                "el => ({tag: el.tagName.toLowerCase(), type: el.type || el.getAttribute('type') || '', text: (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || el.value || '').trim(), href: el.tagName.toLowerCase() === 'a' ? el.href : ''})"
            )
            label = str(details.get("text", ""))
            if details.get("type", "").lower() == "submit" or BLOCKED_ACTION_TERMS.search(label):
                raise BrowserPolicyError(
                    "Click blocked: submit or consequential actions require a human-operated test environment."
                )
            href = details.get("href")
            if href:
                try:
                    self._validate_url(href)
                except URLPolicyError as exc:
                    raise BrowserPolicyError(f"External link click blocked: {exc}") from exc
            await locator.click(timeout=self.settings.action_timeout_ms)
            return f"Clicked a permitted element ({details.get('tag')}).", None

        raise BrowserExecutionError(f"Unsupported action '{step.action}'.")

    async def _prepare_screenshot(self, page: Page) -> None:
        # Best-effort visual masking. The app should still avoid collecting secrets.
        await page.add_style_tag(
            content="input[type=password],input[type=email],input[type=tel],input[autocomplete*=cc- i],[name*=email i],[name*=phone i],[name*=ssn i],[data-private='true'] { filter: blur(8px) !important; }"
        )

    async def run(self, scenario: ScenarioRequest, run_id: UUID | None = None) -> RunReport:
        run_id = run_id or uuid4()
        started_at = _now()
        started_clock = time.perf_counter()
        run_dir = self.settings.artifacts_dir / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = run_dir / "screenshot.png"
        trace_path = run_dir / "trace.zip"
        steps: list[StepRecord] = []
        findings: list[Finding] = []
        console_events: list[str] = []
        network_events: list[str] = []
        finished_at = started_at
        run_status = RunStatus.RUNNING
        summary = "Browser QA run started."
        browser: Browser | None = None
        context: BrowserContext | None = None
        trace_started = False
        planner_provider = self.planner.name
        last_url: str | None = None

        def add_finding(category: str, severity: str, title: str, description: str, url: str | None = None, step_number: int | None = None) -> None:
            findings.append(Finding(
                finding_id=f"F{len(findings) + 1:03d}", category=category,
                severity=severity, title=title,
                description=redact_sensitive_text(description, 1000),
                url=self._safe_url(url), step_number=step_number,
            ))

        try:
            target_url = self._validate_url(scenario.target_url)
            async with async_playwright() as playwright:
                async with asyncio.timeout(self.settings.max_run_seconds):
                    launch_options: dict[str, Any] = {"headless": self.settings.browser_headless}
                    if self.settings.browser_executable_path:
                        launch_options["executable_path"] = self.settings.browser_executable_path
                        launch_options["args"] = ["--no-sandbox"]
                    browser = await playwright.chromium.launch(**launch_options)
                    context = await browser.new_context(
                        viewport={"width": 1440, "height": 1000},
                        ignore_https_errors=False,
                        accept_downloads=False,
                        service_workers="block",
                    )
                    await context.tracing.start(screenshots=True, snapshots=True, sources=False)
                    trace_started = True
                    page = await context.new_page()
                    page.set_default_timeout(self.settings.action_timeout_ms)

                    page.on("console", lambda msg: console_events.append(redact_sensitive_text(msg.text, 800)) if msg.type == "error" else None)
                    page.on("pageerror", lambda error: add_finding("page_error", "high", "Unhandled browser exception", str(error), page.url))
                    page.on("requestfailed", lambda request: network_events.append(redact_sensitive_text(f"{request.method} {self._safe_url(request.url)}: {request.failure}", 800)))
                    page.on("response", lambda response: network_events.append(f"HTTP {response.status} {self._safe_url(response.url)}") if response.status >= 400 else None)

                    async def guard_request(route):
                        request_url = route.request.url
                        if request_url.startswith(("data:", "blob:", "about:")):
                            await route.continue_()
                            return
                        try:
                            self._validate_url(request_url)
                        except URLPolicyError as exc:
                            network_events.append(f"Blocked request to non-allowlisted destination: {self._safe_url(request_url)}")
                            await route.abort(error_code="blockedbyclient")
                            add_finding("security_policy", "medium", "Outbound request blocked", str(exc), request_url)
                        else:
                            await route.continue_()

                    await context.route("**/*", guard_request)

                    async def guard_websocket(websocket_route):
                        websocket_url = websocket_route.url
                        validation_url = websocket_url.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
                        try:
                            self._validate_url(validation_url)
                        except URLPolicyError as exc:
                            network_events.append(
                                f"Blocked WebSocket connection: {self._safe_url(validation_url)}"
                            )
                            add_finding(
                                "security_policy", "medium", "WebSocket connection blocked",
                                str(exc), validation_url,
                            )
                            await websocket_route.close(code=1008, reason="Target is outside the approved host policy.")
                        else:
                            websocket_route.connect_to_server()

                    await context.route_web_socket("**/*", guard_websocket)
                    response = await page.goto(target_url, wait_until="domcontentloaded", timeout=self.settings.navigation_timeout_ms)
                    last_url = page.url
                    if response and response.status >= 400:
                        add_finding("http_error", "high" if response.status >= 500 else "medium", f"Target returned HTTP {response.status}", f"The initial navigation returned HTTP {response.status}.", page.url)

                    completed: list[dict[str, str]] = []
                    source_steps = scenario.steps
                    for index in range(scenario.max_steps):
                        if source_steps is not None:
                            if index >= len(source_steps):
                                break
                            planned = source_steps[index]
                            planner_provider = "user-defined"
                        else:
                            snapshot = await self._snapshot(page)
                            planned = await self.planner.next_action(
                                scenario.objective, snapshot, completed, scenario.expected_title
                            )
                        if planned.action == "finish":
                            break

                        step_started = _now()
                        step_clock = time.perf_counter()
                        try:
                            description, screenshot = await self._execute_action(page, planned, screenshot_path)
                            step_status = StepStatus.PASSED
                            error = None
                            completed.append({"action": planned.action, "status": "passed", "description": description})
                        except (URLPolicyError, BrowserPolicyError) as exc:
                            step_status = StepStatus.BLOCKED
                            error = str(exc)
                            description = planned.note or planned.action
                            screenshot = None
                            add_finding("security_policy", "high", "Browser action blocked by safety policy", error, page.url, index + 1)
                        except Exception as exc:
                            step_status = StepStatus.FAILED
                            error = redact_sensitive_text(f"{type(exc).__name__}: {exc}", 1000)
                            description = planned.note or planned.action
                            screenshot = None
                            add_finding("agent_assertion", "high", "QA step failed", error, page.url, index + 1)
                        steps.append(StepRecord(
                            step_number=index + 1, action=planned.action,
                            description=redact_sensitive_text(planned.note or description, 500), status=step_status,
                            started_at=step_started, finished_at=_now(),
                            duration_ms=int((time.perf_counter() - step_clock) * 1000),
                            error=error, screenshot=screenshot,
                        ))
                        if step_status != StepStatus.PASSED:
                            break

                    last_url = page.url
                    if console_events:
                        for event in console_events[:25]:
                            add_finding("console_error", "medium", "Browser console error", event, last_url)
                    if network_events:
                        for event in network_events[:25]:
                            if event.startswith("HTTP 5"):
                                add_finding("http_error", "high", "Failed network response", event, last_url)
                            elif event.startswith("HTTP 4"):
                                add_finding("http_error", "medium", "Client error response", event, last_url)
                            elif event.startswith("Blocked request"):
                                continue  # Already represented as a security-policy finding.
                            else:
                                add_finding("request_failed", "medium", "Browser request failed", event, last_url)

                    if any(step.status == StepStatus.BLOCKED for step in steps):
                        run_status = RunStatus.BLOCKED
                    elif any(step.status == StepStatus.FAILED for step in steps) or any(f.severity in {"critical", "high"} for f in findings):
                        run_status = RunStatus.FAILED
                    else:
                        run_status = RunStatus.PASSED
                    summary = f"Completed {len(steps)} browser steps with {len(findings)} findings."

                    if context and trace_started:
                        await context.tracing.stop(path=str(trace_path))
                        trace_started = False

        except URLPolicyError as exc:
            run_status = RunStatus.BLOCKED
            summary = f"Run blocked by target URL policy: {exc}"
            add_finding("security_policy", "critical", "Target URL rejected", str(exc), scenario.target_url)
        except Exception as exc:
            run_status = RunStatus.FAILED
            summary = f"Browser QA run failed: {type(exc).__name__}: {exc}"
            add_finding("runtime_error", "high", "Browser runner failure", summary, last_url or scenario.target_url)
        finally:
            if context and trace_started:
                try:
                    await context.tracing.stop(path=str(trace_path))
                except Exception as exc:
                    add_finding("runtime_error", "low", "Trace export failed", str(exc), last_url)
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

        finished_at = _now()
        duration_ms = int((time.perf_counter() - started_clock) * 1000)
        artifacts: dict[str, str] = {}
        if screenshot_path.exists():
            artifacts["screenshot"] = f"/runs/{run_id}/artifacts/screenshot.png"
        if trace_path.exists():
            artifacts["trace"] = f"/runs/{run_id}/artifacts/trace.zip"
        return RunReport(
            run_id=run_id, title=scenario.title, objective=scenario.objective,
            target_url=self._safe_url(last_url or scenario.target_url) or "", status=run_status,
            started_at=started_at, finished_at=finished_at, duration_ms=duration_ms,
            steps=steps, findings=findings, browser_console=console_events[:50],
            network_events=network_events[:100], summary=summary,
            artifacts=artifacts, planner_provider=planner_provider,
        )
