from __future__ import annotations

import argparse
import asyncio
from uuid import uuid4

from app.core.config import settings
from app.models.schemas import ScenarioRequest
from app.services.browser_runner import BrowserQARunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an autonomous browser QA scenario.")
    parser.add_argument("--title", default="Local browser smoke test")
    parser.add_argument("--url", default="http://127.0.0.1:8000/demo")
    parser.add_argument("--objective", default="Verify that the demo page loads and displays its main heading.")
    parser.add_argument("--expected-title", default=None)
    args = parser.parse_args()

    async def execute() -> None:
        runner = BrowserQARunner(settings)
        scenario = ScenarioRequest(
            title=args.title,
            target_url=args.url,
            objective=args.objective,
            expected_title=args.expected_title,
        )
        report = await runner.run(scenario, uuid4())
        print(report.model_dump_json(indent=2))

    asyncio.run(execute())
