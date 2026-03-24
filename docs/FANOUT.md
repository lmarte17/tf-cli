# Fanout

`tinyfish fanout` is a generic bounded-concurrency executor for LLM agents and humans who want to run many TinyFish automations in parallel without hard-coding the workflow to pricing, scraping, form filling, or any other single use case.

It works by:

1. loading a task plan from JSON
2. starting each task with TinyFish `POST /v1/automation/run-async`
3. polling `GET /v1/runs/{id}` until each run reaches a terminal state
4. enforcing a client-side concurrency cap such as `5`
5. returning one aggregated JSON result envelope

This design matches TinyFish's documented async pattern for batches and long-running tasks:

- [Async Bulk Requests](https://docs.tinyfish.ai/examples/bulk-requests-async)
- [Runs lifecycle](https://docs.tinyfish.ai/key-concepts/runs)
- [Start automation asynchronously](https://docs.tinyfish.ai/api-reference/automation/start-automation-asynchronously)

## Commands

List the machine-readable schema surfaces:

```bash
python3 bin/tinyfish fanout schema input
python3 bin/tinyfish fanout schema output
python3 bin/tinyfish fanout schema example
```

Validate and normalize a task plan before running it:

```bash
python3 bin/tinyfish fanout validate --input ./tasks.json --pretty
```

Run a plan with at most 5 active TinyFish runs:

```bash
python3 bin/tinyfish fanout run \
  --input ./tasks.json \
  --max-concurrency 5 \
  --pretty
```

Run only selected tasks:

```bash
python3 bin/tinyfish fanout run \
  --input ./tasks.json \
  --task amazon \
  --task bestbuy \
  --max-concurrency 5 \
  --pretty
```

## Input Shape

The primary input format is an object:

```json
{
  "name": "multi-site-checks",
  "description": "Compare product info across sites",
  "request_defaults": {
    "browser_profile": "lite",
    "api_integration": "openclaw"
  },
  "tasks": [
    {
      "id": "site-a",
      "meta": {
        "site": "site-a",
        "item": "Sony WH-1000XM5"
      },
      "request": {
        "url": "https://example.com/a",
        "goal": "Return JSON only with {\"title\":\"...\",\"price\":\"...\"}"
      }
    }
  ]
}
```

### Top-Level Fields

- `name`: optional string label for the overall fanout job
- `description`: optional string description
- `request_defaults`: optional object merged into every task's `request`
- `tasks`: required non-empty array of task objects

### Task Fields

- `id`: required stable task identifier
- `meta`: optional arbitrary JSON object copied through to output
- `request`: required TinyFish async run request object

### Request Expectations

Each task `request` must at minimum include:

- `url`
- `goal`

It may also include documented TinyFish fields such as:

- `browser_profile`
- `proxy_config`
- `api_integration`
- `feature_flags`
- `use_vault`
- `credential_item_ids`

### Array Shorthand

For agent-generated plans, the CLI also accepts a bare array of task objects:

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

Internally, the CLI normalizes that to `{ "tasks": [...] }`.

## Output Shape

`tinyfish fanout run` returns one aggregated JSON object:

```json
{
  "job": {
    "name": "multi-site-checks",
    "description": "Compare product info across sites",
    "started_at": "2026-03-24T12:00:00+00:00",
    "finished_at": "2026-03-24T12:00:21+00:00",
    "max_concurrency": 5,
    "interval_seconds": 2.0,
    "wait_timeout_seconds": 300.0,
    "fail_fast": false,
    "requested_tasks": 3,
    "executed_task_ids": ["site-a", "site-b", "site-c"]
  },
  "summary": {
    "total": 3,
    "completed": 2,
    "failed": 1,
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
        "item": "Sony WH-1000XM5"
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
        "title": "Sony WH-1000XM5",
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

### Result Semantics

- `outcome` is the executor-level status for the task
- `run_status` is the final TinyFish run status when a run was created successfully
- `result` is the TinyFish `result`, with JSON strings parsed into objects/arrays when possible
- `error` is the TinyFish error object, or a CLI-generated error object for orchestration failures

Possible `outcome` values:

- `COMPLETED`
- `FAILED`
- `CANCELLED`
- `RUN_CREATION_FAILED`
- `WAIT_TIMEOUT`
- `POLLING_ERROR`

## Execution Semantics

- The concurrency limit is enforced client-side by this CLI, not by a documented TinyFish server-side concurrency setting.
- The executor uses TinyFish async runs rather than sync `/run`, which avoids long blocking HTTP requests.
- `--fail-fast` stops starting new tasks after the first failure, but it does not retroactively cancel tasks that were already started.
- Polling defaults to every `2` seconds and can be changed with `--interval`.
- Per-task timeout defaults to `300` seconds and can be changed with `--wait-timeout`.

## Agent Guidance

For best results with LLM agents:

- make every task `goal` request JSON-only output
- define a stable object shape inside the goal
- put non-execution metadata in `meta`, not inside the goal text
- use `request_defaults` for shared fields like `browser_profile` and `api_integration`
- use `fanout validate` before `fanout run` when plans are generated dynamically

## Common Patterns

This executor is intentionally generic. It can drive:

- price gathering across many sites
- lead enrichment across directories
- policy checks across many pages
- repeated QA flows across multiple environments
- catalog extraction across many categories
- content moderation checks across many URLs
