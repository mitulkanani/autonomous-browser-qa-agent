import pytest
from pydantic import ValidationError

from app.models.schemas import AgentStep, LocatorSpec, ScenarioRequest
from app.services.planner import MockPlanner


def test_role_locator_requires_role() -> None:
    with pytest.raises(ValidationError):
        LocatorSpec(strategy="role", value="Continue")


def test_fill_action_requires_locator_and_value() -> None:
    with pytest.raises(ValidationError):
        AgentStep(action="fill", value="hello")
    with pytest.raises(ValidationError):
        AgentStep(action="fill", locator={"strategy": "label", "value": "Name"})


def test_scenario_rejects_too_many_steps() -> None:
    with pytest.raises(ValidationError):
        ScenarioRequest(
            title="Bad scenario", target_url="https://qa.example.com",
            objective="Check page", max_steps=13,
        )


@pytest.mark.asyncio
async def test_mock_planner_asserts_heading_then_screenshots_then_finishes() -> None:
    planner = MockPlanner()
    snapshot = {"title": "Demo", "interactive_elements": [], "visible_text": ""}
    first = await planner.next_action("Check homepage", snapshot, [])
    second = await planner.next_action("Check homepage", snapshot, [{"action": first.action}])
    third = await planner.next_action("Check homepage", snapshot, [{"action": "assert_visible"}, {"action": "screenshot"}])
    assert first.action == "assert_visible"
    assert second.action == "screenshot"
    assert third.action == "finish"


def test_agent_step_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AgentStep.model_validate({"action": "finish", "python_code": "print('no')"})
