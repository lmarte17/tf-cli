# tinyfish-cli

`tinyfish-cli` is an agent-friendly command-line interface for the TinyFish browser automation API.

It is designed to work well for LLM agents like OpenClaw while still being comfortable for humans:

- compact JSON output by default
- `--pretty` output for interactive use
- stdin/file-based JSON inputs
- async, SSE, batch, fanout, and suite workflows
- stable input and output shapes for orchestration

The implementation is based on TinyFish's public docs and OpenAPI spec:

- [Authentication](https://docs.tinyfish.ai/authentication)
- [Run browser automation with SSE streaming](https://docs.tinyfish.ai/api-reference/automation/run-browser-automation-with-sse-streaming)
- [Start automation asynchronously](https://docs.tinyfish.ai/api-reference/automation/start-automation-asynchronously)
- [Start multiple automations asynchronously](https://docs.tinyfish.ai/api-reference/automation/start-multiple-automations-asynchronously)
- [Runs](https://docs.tinyfish.ai/key-concepts/runs)
- [OpenAPI spec](https://agent.tinyfish.ai/v1/openapi.json?v=2026-02-23)

## Features

- `auth` commands for saving and inspecting your API key
- `run`, `run-async`, `run-sse`, and `run-batch`
- `runs list|get|get-many|wait|cancel|cancel-many`
- `browser create|usage`
- `fanout` for bounded-concurrency orchestration
- `suite` for built-in and custom integration tests
- `agent run ...` aliases for agent-oriented callers

## Requirements

- Python `3.9+`
- a TinyFish API key

This project uses only the Python standard library at runtime.

## Installation

### Option 1: use the repo-local wrapper

No installation step is required:

```bash
./bin/tinyfish --help
```

You can also invoke it explicitly with Python:

```bash
python3 bin/tinyfish --help
```

### Option 2: install into a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
tinyfish --help
```

Once the package is published to PyPI, installation becomes:

```bash
python3 -m pip install tinyfish-cli
```

## Authentication

The CLI resolves the API key in this order:

1. `--api-key`
2. `TINYFISH_API_KEY`
3. `~/.tinyfish/config.json`

Default config path:

```text
~/.tinyfish/config.json
```

Store a key interactively:

```bash
./bin/tinyfish auth login
```

Store a key directly:

```bash
./bin/tinyfish auth set tf_your_key_here
```

Store a key from stdin:

```bash
printf '%s' "$TINYFISH_API_KEY" | ./bin/tinyfish auth set
```

Check auth status:

```bash
./bin/tinyfish auth status --pretty
```

Remove the saved key:

```bash
./bin/tinyfish auth logout --pretty
```

`auth status` exits with code `0` when authenticated and `1` when no key is available.

## Quick Start

Set your key for the current shell:

```bash
export TINYFISH_API_KEY="tf_your_real_key"
```

Verify the CLI sees it:

```bash
./bin/tinyfish auth status --pretty
```

Try a read-only API call:

```bash
./bin/tinyfish runs list --limit 1 --pretty
```

Run a simple automation:

```bash
./bin/tinyfish run \
  --url https://example.com \
  --goal "Return JSON only with {\"title\":\"...\"}" \
  --pretty
```

For longer jobs, prefer `run-async` or `run-sse` instead of synchronous `run`.

## Output Model

By default, commands emit compact JSON on stdout. Add `--pretty` to indent output for human use.

Errors are emitted as JSON on stderr in this shape:

```json
{
  "error": {
    "code": "SOME_CODE",
    "message": "Human-readable error",
    "status": 401,
    "details": {
      "any": "extra context"
    }
  }
}
```

When TinyFish itself returns a structured `error` object, the CLI preserves that shape where possible.

## Command Reference

Top-level commands:

```bash
./bin/tinyfish --help
```

```text
auth
run
run-async
run-sse
run-batch
runs
browser
fanout
suite
```

### `run`

Runs a synchronous TinyFish automation against `POST /v1/automation/run`.

Example:

```bash
./bin/tinyfish run \
  --url https://example.com \
  --goal "Return JSON only with {\"title\":\"...\",\"links\":[]}" \
  --browser-profile lite \
  --api-integration openclaw \
  --pretty
```

Supported flag-driven request fields:

- `--url`
- `--goal`
- `--browser-profile lite|stealth`
- `--proxy-enabled` or `--no-proxy-enabled`
- `--proxy-country US|GB|CA|DE|FR|JP|AU`
- `--api-integration`
- `--enable-agent-memory` or `--no-enable-agent-memory`
- `--use-vault` or `--no-use-vault`
- `--credential-item-id` repeated

You can also provide a full JSON object with `--input` and optionally override fields with flags:

```bash
cat <<'JSON' | ./bin/tinyfish run --input - --pretty
{
  "url": "https://example.com",
  "goal": "Return JSON only with {\"title\":\"...\"}",
  "browser_profile": "lite",
  "proxy_config": {
    "enabled": true,
    "country_code": "US"
  },
  "api_integration": "openclaw",
  "feature_flags": {
    "enable_agent_memory": true
  },
  "use_vault": true,
  "credential_item_ids": ["cred_123"]
}
JSON
```

### `run-async`

Starts an async TinyFish automation with `POST /v1/automation/run-async`.

Example:

```bash
./bin/tinyfish run-async \
  --url https://example.com \
  --goal "Return JSON only with {\"title\":\"...\"}" \
  --pretty
```

Typical follow-up:

```bash
./bin/tinyfish runs wait RUN_ID --pretty
```

### `run-sse`

Runs a TinyFish automation via SSE streaming.

Example:

```bash
./bin/tinyfish run-sse \
  --url https://example.com \
  --goal "Return JSON only with {\"title\":\"...\"}" \
  --pretty
```

In `--pretty` mode, the CLI prints readable progress lines such as:

- `[started]`
- `[live]`
- `[progress]`
- `[complete]`

Show heartbeat events too:

```bash
./bin/tinyfish run-sse \
  --url https://example.com \
  --goal "Return JSON only with {\"title\":\"...\"}" \
  --show-heartbeats \
  --pretty
```

Without `--pretty`, each SSE event is emitted as compact JSON.

### `run-batch`

Starts multiple async runs at once with `POST /v1/automation/run-batch`.

Input can be either:

- a JSON array of run request objects
- an object with a top-level `runs` array

Example array input:

```bash
cat <<'JSON' | ./bin/tinyfish run-batch --input - --pretty
[
  {
    "url": "https://example.com/a",
    "goal": "Return JSON only with {\"site\":\"a\"}"
  },
  {
    "url": "https://example.com/b",
    "goal": "Return JSON only with {\"site\":\"b\"}"
  }
]
JSON
```

### `runs`

Inspect and manage existing runs.

List runs:

```bash
./bin/tinyfish runs list --limit 10 --pretty
```

Filter runs:

```bash
./bin/tinyfish runs list \
  --status COMPLETED \
  --goal "Return JSON only" \
  --sort-direction desc \
  --limit 5 \
  --pretty
```

Get one run:

```bash
./bin/tinyfish runs get RUN_ID --pretty
```

Get many runs:

```bash
./bin/tinyfish runs get-many RUN_1 RUN_2 RUN_3 --pretty
```

Or from JSON:

```bash
cat <<'JSON' | ./bin/tinyfish runs get-many --input - --pretty
{
  "run_ids": ["RUN_1", "RUN_2"]
}
JSON
```

Wait for a run to finish:

```bash
./bin/tinyfish runs wait RUN_ID --interval 2 --wait-timeout 300 --pretty
```

Cancel one run:

```bash
./bin/tinyfish runs cancel RUN_ID --pretty
```

Cancel many runs:

```bash
./bin/tinyfish runs cancel-many RUN_1 RUN_2 --pretty
```

`runs wait` exits non-zero if the final status is `FAILED` or `CANCELLED`.

### `browser`

Remote browser session utilities.

Create a browser session:

```bash
./bin/tinyfish browser create --pretty
```

List browser usage:

```bash
./bin/tinyfish browser usage --limit 20 --pretty
```

Filter browser usage:

```bash
./bin/tinyfish browser usage \
  --session-id SESSION_ID \
  --status running \
  --start-after 2026-03-01T00:00:00Z \
  --end-before 2026-03-31T23:59:59Z \
  --limit 20 \
  --page 1 \
  --pretty
```

### `fanout`

`fanout` is a generic bounded-concurrency executor built for independent TinyFish tasks.

It is not pricing-specific, scraping-specific, or ticketing-specific. It lets an external agent decide what the tasks are while this CLI handles:

- async run creation
- client-side concurrency limits
- polling until terminal status
- aggregation into one JSON envelope

Print machine-readable schemas:

```bash
./bin/tinyfish fanout schema input
./bin/tinyfish fanout schema output
./bin/tinyfish fanout schema example
```

Validate a plan:

```bash
./bin/tinyfish fanout validate --input ./examples/fanout-template.json --pretty
```

Run a plan with up to 5 active tasks:

```bash
./bin/tinyfish fanout run \
  --input ./examples/fanout-template.json \
  --max-concurrency 5 \
  --pretty
```

Run selected tasks only:

```bash
./bin/tinyfish fanout run \
  --input ./examples/fanout-template.json \
  --task site-a \
  --task site-b \
  --max-concurrency 5 \
  --pretty
```

Detailed fanout docs live in [docs/FANOUT.md](https://github.com/lmarte17/tf-cli/blob/main/docs/FANOUT.md).

### `suite`

Suites are live TinyFish smoke tests with assertions on the final run payload.

List built-in suites:

```bash
./bin/tinyfish suite list --pretty
```

Show a suite definition:

```bash
./bin/tinyfish suite show common-web --pretty
```

Run the built-in suite:

```bash
./bin/tinyfish suite run common-web --pretty
```

Run a single scenario:

```bash
./bin/tinyfish suite run common-web --scenario cart-addition --pretty
```

Run the built-in suite in fanout mode:

```bash
./bin/tinyfish suite run common-web \
  --fanout \
  --fanout-duplicates 2 \
  --fanout-max-concurrency 5 \
  --pretty
```

The built-in `common-web` suite covers:

- multi-page research on [Books to Scrape](https://books.toscrape.com/)
- cart interaction on [Sauce Demo](https://www.saucedemo.com/)
- form fill and submit on [Selenium Web Form](https://www.selenium.dev/selenium/web/web-form.html)

In fanout mode, each selected scenario is duplicated into task IDs like `cart-addition--1` and `cart-addition--2`, executed concurrently through the generic fanout executor, and then validated with the original suite assertions.

## Agent Aliases

For agent-oriented integrations, the CLI also accepts `agent run ...` aliases.

These map as follows:

- `tinyfish agent run ...` -> `tinyfish run ...`
- `tinyfish agent run async ...` -> `tinyfish run-async ...`
- `tinyfish agent run sse ...` -> `tinyfish run-sse ...`
- `tinyfish agent run batch ...` -> `tinyfish run-batch ...`
- `tinyfish agent run list ...` -> `tinyfish runs list ...`
- `tinyfish agent run get ...` -> `tinyfish runs get ...`
- `tinyfish agent run get-many ...` -> `tinyfish runs get-many ...`
- `tinyfish agent run wait ...` -> `tinyfish runs wait ...`
- `tinyfish agent run cancel ...` -> `tinyfish runs cancel ...`
- `tinyfish agent run cancel-many ...` -> `tinyfish runs cancel-many ...`

Examples:

```bash
./bin/tinyfish agent run \
  --url https://example.com \
  --goal "Return JSON only with {\"title\":\"...\"}" \
  --pretty
```

```bash
./bin/tinyfish agent run async \
  --url https://example.com \
  --goal "Return JSON only with {\"title\":\"...\"}" \
  --pretty
```

```bash
./bin/tinyfish agent run list --limit 5 --pretty
```

## Agent-Friendly Input Patterns

### Single-run input shape

Single-run commands accept a JSON object with TinyFish request fields.

Minimum required fields:

```json
{
  "url": "https://example.com",
  "goal": "Return JSON only with {\"title\":\"...\"}"
}
```

Common optional fields:

```json
{
  "url": "https://example.com",
  "goal": "Return JSON only with {\"title\":\"...\"}",
  "browser_profile": "lite",
  "proxy_config": {
    "enabled": true,
    "country_code": "US"
  },
  "api_integration": "openclaw",
  "feature_flags": {
    "enable_agent_memory": true
  },
  "use_vault": true,
  "credential_item_ids": ["cred_123"]
}
```

### Batch input shape

Accepted by `run-batch`:

```json
{
  "runs": [
    {
      "url": "https://example.com/a",
      "goal": "Return JSON only with {\"site\":\"a\"}"
    },
    {
      "url": "https://example.com/b",
      "goal": "Return JSON only with {\"site\":\"b\"}"
    }
  ]
}
```

or:

```json
[
  {
    "url": "https://example.com/a",
    "goal": "Return JSON only with {\"site\":\"a\"}"
  }
]
```

### Fanout input shape

Accepted by `fanout validate` and `fanout run`:

```json
{
  "name": "multi-site-checks",
  "description": "Generic concurrent TinyFish task plan.",
  "request_defaults": {
    "browser_profile": "lite",
    "api_integration": "openclaw"
  },
  "tasks": [
    {
      "id": "site-a",
      "meta": {
        "site": "site-a",
        "kind": "lookup"
      },
      "request": {
        "url": "https://example.com/a",
        "goal": "Return JSON only with {\"title\":\"...\",\"price\":\"...\"}"
      }
    }
  ]
}
```

Top-level fields:

- `name`: optional string
- `description`: optional string
- `request_defaults`: optional object merged into each task request
- `tasks`: required non-empty array

Task fields:

- `id`: required stable identifier
- `meta`: optional object carried through to output
- `request`: required TinyFish async request object with at least `url` and `goal`

Array shorthand is also accepted:

```json
[
  {
    "id": "task-1",
    "request": {
      "url": "https://example.com/1",
      "goal": "Return JSON only with {\"title\":\"...\"}"
    }
  }
]
```

### Fanout output shape

`fanout run` returns one aggregated JSON object:

```json
{
  "job": {
    "name": "multi-site-checks",
    "description": "Generic concurrent TinyFish task plan.",
    "started_at": "2026-03-24T12:00:00+00:00",
    "finished_at": "2026-03-24T12:00:21+00:00",
    "max_concurrency": 5,
    "interval_seconds": 2.0,
    "wait_timeout_seconds": 300.0,
    "fail_fast": false,
    "requested_tasks": 2,
    "executed_task_ids": ["site-a", "site-b"]
  },
  "summary": {
    "total": 2,
    "completed": 2,
    "failed": 0,
    "cancelled": 0,
    "run_creation_failed": 0,
    "wait_timeout": 0,
    "polling_error": 0
  },
  "results": [
    {
      "id": "site-a",
      "meta": {
        "site": "site-a",
        "kind": "lookup"
      },
      "request": {
        "url": "https://example.com/a",
        "goal": "Return JSON only with {\"title\":\"...\",\"price\":\"...\"}",
        "browser_profile": "lite",
        "api_integration": "openclaw"
      },
      "run_id": "run_abc123",
      "outcome": "COMPLETED",
      "run_status": "COMPLETED",
      "result": {
        "title": "Example Product",
        "price": "$349.99"
      },
      "error": null,
      "duration_seconds": 12.418,
      "run_response": {
        "...": "..."
      }
    }
  ]
}
```

Result semantics:

- `outcome` is the executor-level outcome
- `run_status` is the TinyFish terminal status when a run exists
- `result` is the TinyFish `result`, with JSON strings parsed into objects or arrays when possible
- `error` is either a TinyFish error object or a CLI-generated orchestration error

Possible `outcome` values:

- `COMPLETED`
- `FAILED`
- `CANCELLED`
- `RUN_CREATION_FAILED`
- `WAIT_TIMEOUT`
- `POLLING_ERROR`

### Custom suite shape

A custom suite is a JSON object with a `scenarios` array:

```json
{
  "name": "my-suite",
  "description": "Custom TinyFish smoke tests",
  "scenarios": [
    {
      "id": "form-check",
      "description": "Fill a form and confirm success",
      "request": {
        "url": "https://example.com/form",
        "goal": "Return JSON only with {\"submitted\":true,\"message\":\"...\"}"
      },
      "assertions": [
        {
          "type": "equals",
          "path": "status",
          "value": "COMPLETED"
        },
        {
          "type": "truthy",
          "path": "result.submitted"
        },
        {
          "type": "contains",
          "path": "result.message",
          "value": "Success"
        }
      ]
    }
  ]
}
```

Custom suite requirements:

- top-level object
- non-empty `scenarios` array
- each scenario must have a unique string `id`
- each scenario must include a `request` object with `url` and `goal`
- `assertions` must be an array if present

Supported assertion types:

- `equals`
- `truthy`
- `contains`
- `contains_all`
- `min_items`
- `type`
- `all_items_have_keys`

Supported path syntax:

- dotted object paths like `result.message`
- list indexes like `result.items.0.title`

Run a custom suite:

```bash
./bin/tinyfish suite run --file ./my-suite.json --pretty
```

## Operational Guidance

For LLM agents, these patterns work best:

- ask TinyFish to return JSON only
- define the expected object shape explicitly in the `goal`
- put orchestration metadata in `meta`, not inside the prompt text
- use `api_integration` to identify the caller, for example `openclaw`
- use `run-async` or `fanout run` for long or concurrent jobs
- omit `--pretty` when another program is parsing stdout

Recommended pattern for a single long-running job:

```bash
./bin/tinyfish run-async \
  --url https://example.com \
  --goal "Return JSON only with {\"title\":\"...\"}" \
  --pretty
./bin/tinyfish runs wait RUN_ID --pretty
```

Recommended pattern for many independent jobs:

```bash
./bin/tinyfish fanout run \
  --input ./examples/fanout-template.json \
  --max-concurrency 5 \
  --pretty
```

If you need application-specific workflow logic such as approvals, deduplication, dependencies, or post-run reconciliation, keep that logic outside this CLI and treat `tinyfish-cli` as the execution layer.

## Failure Semantics

- `run` returns the final TinyFish response when the HTTP request completes normally.
- `run-async` returns the run creation response.
- `run-sse` exits non-zero if the stream ends before `COMPLETE`, or if the final status is `FAILED` or `CANCELLED`.
- `runs wait` exits non-zero if the final status is `FAILED` or `CANCELLED`.
- `fanout run` exits non-zero if any task ends in `FAILED`, `CANCELLED`, `RUN_CREATION_FAILED`, `WAIT_TIMEOUT`, or `POLLING_ERROR`.
- `suite run` exits non-zero if any scenario fails validation or cannot complete successfully.

The synchronous `run` command can encounter network disconnects on long jobs even when the run succeeded server-side. This CLI wraps that case as a `REMOTE_DISCONNECTED` error and includes guidance to prefer `run-async` or `run-sse`.

## Development

Run the test suite:

```bash
python3 -m unittest discover -s tests -v
```

Helpful smoke checks:

```bash
python3 bin/tinyfish --help
python3 bin/tinyfish suite run --help
python3 bin/tinyfish fanout schema input
```

## Publishing To PyPI

As of March 24, 2026, the package name `tinyfish-cli` was available on PyPI.

Build distributions:

```bash
python3 -m venv .venv-publish
source .venv-publish/bin/activate
python3 -m pip install --upgrade pip build twine
python3 -m build
python3 -m twine check dist/*
```

Upload to PyPI:

```bash
python3 -m twine upload dist/*
```

Upload to TestPyPI first if you want a dry run:

```bash
python3 -m twine upload --repository testpypi dist/*
```

You will need a PyPI account and either an API token or Trusted Publishing configured for the repository.

## Project Layout

```text
bin/tinyfish                    repo-local runner
src/tinyfish_cli/cli.py         command parsing and handlers
src/tinyfish_cli/client.py      HTTP and SSE client
src/tinyfish_cli/fanout.py      bounded-concurrency executor
src/tinyfish_cli/suite_runner.py suite loading and execution
src/tinyfish_cli/builtin_suites.py built-in live smoke suites
docs/FANOUT.md                  detailed fanout documentation
examples/fanout-template.json   starter fanout plan
LICENSE                        package license
MANIFEST.in                    source distribution include rules
tests/                          unit tests
```

## License

MIT
