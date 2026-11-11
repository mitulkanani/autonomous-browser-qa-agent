from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class StepStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class LocatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["role", "text", "label", "placeholder", "test_id", "css"]
    value: str = Field(min_length=1, max_length=300)
    role: str | None = Field(default=None, max_length=40)
    exact: bool = False

    @model_validator(mode="after")
    def role_is_required_for_role_strategy(self) -> "LocatorSpec":
        if self.strategy == "role" and not self.role:
            raise ValueError("role is required when strategy='role'.")
        return self


class AgentStep(BaseModel):
    """A constrained browser action. Arbitrary code and arbitrary JS are never accepted."""

    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "click",
        "fill",
        "assert_text",
        "assert_visible",
        "assert_title",
        "screenshot",
        "finish",
    ]
    locator: LocatorSpec | None = None
    expected: str | None = Field(default=None, max_length=500)
    value: str | None = Field(default=None, max_length=1000)
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_action_arguments(self) -> "AgentStep":
        if self.action in {"click", "fill", "assert_visible"} and self.locator is None:
            raise ValueError(f"locator is required for action '{self.action}'.")
        if self.action == "fill" and self.value is None:
            raise ValueError("value is required for action 'fill'.")
        if self.action in {"assert_text", "assert_title"} and not self.expected:
            raise ValueError(f"expected is required for action '{self.action}'.")
        if self.action == "assert_text" and self.locator is None:
            raise ValueError("locator is required for action 'assert_text'.")
        return self


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    target_url: str = Field(min_length=8, max_length=2000)
    objective: str = Field(min_length=5, max_length=1200)
    expected_title: str | None = Field(default=None, max_length=300)
    max_steps: int = Field(default=6, ge=1, le=12)
    steps: list[AgentStep] | None = Field(default=None, max_length=12)

    @model_validator(mode="after")
    def steps_fit_maximum(self) -> "ScenarioRequest":
        if self.steps is not None and len(self.steps) > self.max_steps:
            raise ValueError("steps cannot contain more actions than max_steps.")
        return self

class StepRecord(BaseModel):
    step_number: int
    action: str
    description: str
    status: StepStatus
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    error: str | None = None
    screenshot: str | None = None


class Finding(BaseModel):
    finding_id: str
    category: Literal[
        "console_error",
        "page_error",
        "request_failed",
        "http_error",
        "agent_assertion",
        "security_policy",
        "timeout",
        "runtime_error",
    ]
    severity: Literal["critical", "high", "medium", "low", "info"]
    title: str
    description: str
    url: str | None = None
    step_number: int | None = None


class RunReport(BaseModel):
    run_id: UUID
    title: str
    objective: str
    target_url: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    steps: list[StepRecord]
    findings: list[Finding]
    browser_console: list[str]
    network_events: list[str]
    summary: str
    artifacts: dict[str, str] = Field(default_factory=dict)
    planner_provider: str


class RunCreated(BaseModel):
    run_id: UUID
    status: RunStatus
    summary: str
    report_url: str


class RunSummary(BaseModel):
    run_id: UUID
    title: str
    target_url: str
    status: RunStatus
    started_at: datetime
    duration_ms: int
    finding_count: int
