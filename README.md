# Autonomous Browser QA Agent

A safety-first browser testing agent built with **FastAPI, Playwright for Python, and an optional OpenAI planner**. Describe a QA objective, point the agent at an explicitly allowlisted website, and receive structured test steps, browser diagnostics, screenshots, and a Playwright trace.

> **Current scope:** working local QA platform with a constrained action vocabulary, deterministic mock planner, optional LLM planner, and a bundled demo site. This is a developer tool starter—not an unattended production testing service. It does not submit forms, perform purchases, delete data, send messages, or make other consequential changes.

## What it demonstrates

- A FastAPI control plane for creating, listing, and inspecting QA runs.
- A Playwright Chromium worker with isolated browser contexts.
- Agentic planning using a deterministic mock planner or optional OpenAI structured-output planner.
- A constrained action schema: click, fill, assert text, assert visibility, assert title, screenshot, and finish.
- A host allowlist applied before navigation and to every browser HTTP request, including redirects and subresources.
- Private, loopback, link-local, reserved, and unspecified IP blocking unless explicitly enabled for local development.
- Safety checks that block submit buttons, destructive/consequential labels, password inputs, file inputs, and common PII input types.
- Console, page-error, failed-request, HTTP error, and assertion findings.
- Screenshots and Playwright traces for investigation.
- SQLite run history and an optional bearer token for API access.
- Docker, CI tests, and a manual deployment QA GitHub Actions workflow.

## Architecture

```text
Dashboard / API client
        |
        v
     FastAPI
        |
        +---- Scenario validation
        +---- Target URL policy (allowlist + public IP checks)
        |
        v
  Browser QA Runner
        |
        +---- Planner
        |       +---- Mock planner (default)
        |       +---- OpenAI structured-output planner (optional)
        |
        +---- Constrained action executor
        |       +---- click (safe, non-submitting targets only)
        |       +---- fill (non-sensitive inputs only)
        |       +---- assertions
        |       +---- screenshot
        |
        +---- Diagnostics
        |       +---- console errors
        |       +---- page exceptions
        |       +---- failed requests / HTTP errors
        |       +---- Playwright trace
        |
        v
   Report + SQLite history + artifacts
```

## Quick start

Python 3.11 or newer is recommended. The project uses Playwright for Python; install its Chromium browser after installing the Python package.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m playwright install chromium
cp .env.example .env
uvicorn app.main:app --reload
```

Open the dashboard at [http://127.0.0.1:8000](http://127.0.0.1:8000), the API docs at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs), and the bundled target page at [http://127.0.0.1:8000/demo](http://127.0.0.1:8000/demo).

In the dashboard, choose **Use demo** and start a run. The default mock planner checks the expected title (when supplied), verifies the primary heading, captures a screenshot, and finishes. It needs no API key.

### Run from the CLI

Start the FastAPI server in one terminal, then in another:

```bash
browser-qa \
  --title "Demo homepage smoke test" \
  --url "http://127.0.0.1:8000/demo" \
  --objective "Verify that the demo page loads and displays its main heading." \
  --expected-title "QA Demo Store"
```

### Create a run with the API

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Demo homepage smoke test",
    "target_url": "http://127.0.0.1:8000/demo",
    "objective": "Verify the homepage title and main heading.",
    "expected_title": "QA Demo Store",
    "max_steps": 6
  }'
```

Use the returned `run_id` with `GET /runs/{run_id}` to retrieve the report and artifact links.

## Optional OpenAI planner

The OpenAI planner receives a compact page snapshot (page title, visible text, and interactive element labels) and returns one action at a time using a strict Pydantic-derived JSON schema. It is constrained to the supported action vocabulary; the browser runner independently validates every action. The page snapshot can contain information from the target site, so enabling this mode sends that limited snapshot to OpenAI. Do not use it on sensitive pages unless your data-handling requirements allow that transfer.

Install the optional client:

```bash
python -m pip install -e ".[dev,openai]"
```

Set these values in `.env`:

```env
PLANNER_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4.1-mini
```

Restart the API. Use the mock planner for deterministic tests and CI.

## Target host security (read this before pointing it at a site)

The browser worker can navigate and interact with pages. **Never run it as an unrestricted public browsing proxy.**

1. Add only domains you own or are explicitly authorized to test to `ALLOWED_TARGET_HOSTS`.
2. The app checks the hostname and resolves DNS to reject private, loopback, link-local, reserved, and unspecified IP destinations by default.
3. The same URL check is applied to browser requests, including redirects and page resources. Third-party CDNs and API hosts must be explicitly allowlisted if a target needs them.
4. `ALLOW_LOOPBACK_TARGETS=true` is provided only to make the bundled local demo work. Do not enable it on a public deployment. `ALLOW_PRIVATE_TARGETS=true` is a separate, explicit opt-in for RFC1918 private staging networks; link-local and reserved ranges remain blocked.
5. Add network-level egress controls in production. Application-level DNS checks alone cannot fully eliminate DNS rebinding or all browser network side channels.
6. Configure `QA_API_TOKEN` before exposing the API. Put the service behind TLS, authentication, rate limiting, and an isolated worker/container with restricted network egress.
7. Do not point the agent at sites with real customer data, payment flows, or production write privileges. Use a staging tenant with synthetic data.

### Supported actions and guardrails

| Action | Behavior |
|---|---|
| `assert_title` | Checks whether the page title contains expected text |
| `assert_visible` | Checks one visible element by an approved locator |
| `assert_text` | Checks text inside one visible element |
| `screenshot` | Captures a full-page PNG; common sensitive fields are visually blurred as a best effort |
| `fill` | Fills one non-sensitive input; refuses password, file, hidden, email, telephone, numeric, and date fields; entered values are not stored in step logs |
| `click` | Clicks a unique visible element only when it is not a submit button and its label does not indicate a consequential action; external links must pass the host policy |
| `finish` | Ends the agent loop |

No arbitrary JavaScript, shell commands, generated Python, form submission, or arbitrary URL navigation is exposed to the planner.

## Configure target hosts

For example, to test an owned staging host and its asset host:

```env
ALLOWED_TARGET_HOSTS=staging.example.com,assets.example.com
ALLOW_PRIVATE_TARGETS=false
```

Wildcard entries such as `*.example.com` allow that domain and its subdomains. Do not add broad wildcards unless you control the entire DNS zone.

## Browser settings

| Variable | Default | Description |
|---|---|---|
| `ALLOW_LOOPBACK_TARGETS` | `false` | Allow 127.0.0.1 / ::1 targets (local demo only) |
| `ALLOW_PRIVATE_TARGETS` | `false` | Allow RFC1918 private network targets when explicitly needed |
| `BROWSER_HEADLESS` | `true` | Headless Chromium |
| `BROWSER_EXECUTABLE_PATH` | empty | Optional local Chromium executable path |
| `NAVIGATION_TIMEOUT_MS` | `15000` | Initial navigation timeout |
| `ACTION_TIMEOUT_MS` | `7000` | Locator/action timeout |
| `MAX_RUN_SECONDS` | `90` | Documented run ceiling; set deployment request timeouts accordingly |
| `MAX_CONCURRENT_RUNS` | `2` | API concurrency semaphore |
| `DATABASE_PATH` | `./data/qa_runs.sqlite3` | SQLite run history |
| `ARTIFACTS_DIR` | `./artifacts` | Screenshots and traces |

## Run tests

```bash
pytest -q
ruff check app tests
```

The current local verification suite contains 23 passing tests. The Chromium integration tests use a real browser to exercise locator handling, action policies, screenshots, and traces. In restricted environments where outbound navigation is blocked, the tests replace the network navigation call with an in-memory HTML fixture; this does not verify real target-host networking. The CI workflow installs the managed Playwright Chromium browser, and `browser-qa.yml` provides a manual live smoke test for an explicitly allowlisted deployment URL.

## Run with Docker

```bash
cp .env.example .env
docker compose up --build
```

The Compose configuration enables loopback targets so the bundled demo can be tested from inside the container. It does not enable RFC1918 private targets by default. Do not enable either option in a public or shared deployment unless your staging network design requires it. Persistent SQLite data and browser artifacts are stored in named Docker volumes.

## Project layout

```text
app/
  api/routes.py                 # Run and artifact APIs
  core/config.py                # Environment settings
  models/schemas.py             # Scenario, action, finding and report schemas
  services/url_guard.py         # Host allowlist, DNS/IP policy and redaction
  services/planner.py           # Mock and optional OpenAI planner
  services/browser_runner.py    # Playwright worker and constrained executor
  services/storage.py           # SQLite history
  web/                          # Dashboard and demo target site
tests/
  test_url_guard.py
  test_schemas_planner.py
  test_api.py
  test_browser_integration.py
.github/workflows/
  ci.yml
  browser-qa.yml
```

## Known limitations and roadmap

- The planner is a bounded action selector, not an unrestricted general-purpose browser agent.
- The mock planner performs a deterministic smoke test. More complex workflows need explicit scenario steps or the optional OpenAI planner.
- Screenshots blur common sensitive input types as a best-effort measure; this is not a guarantee against sensitive content elsewhere on the page.
- API authentication is an optional shared bearer token. Add SSO/OIDC, tenant-level authorization, audit retention, and secrets management before team deployment.
- SQLite is intended for a small single-instance deployment. Move run data and worker coordination to PostgreSQL/Redis for production scale.
- Add role-specific test credentials through a secrets manager, visual regression baselines, accessibility audits, and cross-browser execution where required.
- Add a human approval workflow before enabling any future action that can submit forms or mutate application data.

## License

MIT. See [LICENSE](LICENSE).
