from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import json
import time
from typing import Any, Deque, Dict, List, Optional, Tuple

from tinyfish_cli.client import TinyFishClient
from tinyfish_cli.errors import CliError


FANOUT_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "TinyFish Fanout Input",
    "description": (
        "Task plan for running multiple TinyFish automations concurrently from the CLI. "
        "The CLI accepts either this object shape or a bare array of task objects."
    ),
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "request_defaults": {
                    "type": "object",
                    "description": "Default TinyFish request fields merged into every task request.",
                    "additionalProperties": True,
                },
                "tasks": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/task"},
                },
            },
            "required": ["tasks"],
            "additionalProperties": False,
        },
        {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/task"},
        },
    ],
    "$defs": {
        "task": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Stable task identifier used in output aggregation.",
                },
                "meta": {
                    "type": "object",
                    "description": "Arbitrary metadata carried through to output.",
                    "additionalProperties": True,
                },
                "request": {
                    "type": "object",
                    "description": "TinyFish automation request payload for /v1/automation/run-async.",
                    "properties": {
                        "url": {"type": "string"},
                        "goal": {"type": "string"},
                        "browser_profile": {"type": "string", "enum": ["lite", "stealth"]},
                        "proxy_config": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "country_code": {"type": "string"},
                            },
                            "additionalProperties": True,
                        },
                        "api_integration": {"type": "string"},
                        "feature_flags": {"type": "object", "additionalProperties": True},
                        "use_vault": {"type": "boolean"},
                        "credential_item_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["url", "goal"],
                    "additionalProperties": True,
                },
            },
            "required": ["id", "request"],
            "additionalProperties": False,
        }
    },
}


FANOUT_OUTPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "TinyFish Fanout Output",
    "type": "object",
    "properties": {
        "job": {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
                "description": {"type": ["string", "null"]},
                "started_at": {"type": "string"},
                "finished_at": {"type": "string"},
                "max_concurrency": {"type": "integer"},
                "interval_seconds": {"type": "number"},
                "wait_timeout_seconds": {"type": "number"},
                "fail_fast": {"type": "boolean"},
                "requested_tasks": {"type": "integer"},
                "executed_task_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "name",
                "description",
                "started_at",
                "finished_at",
                "max_concurrency",
                "interval_seconds",
                "wait_timeout_seconds",
                "fail_fast",
                "requested_tasks",
                "executed_task_ids",
            ],
        },
        "summary": {
            "type": "object",
            "properties": {
                "total": {"type": "integer"},
                "completed": {"type": "integer"},
                "failed": {"type": "integer"},
                "cancelled": {"type": "integer"},
                "run_creation_failed": {"type": "integer"},
                "wait_timeout": {"type": "integer"},
                "polling_error": {"type": "integer"},
            },
            "required": [
                "total",
                "completed",
                "failed",
                "cancelled",
                "run_creation_failed",
                "wait_timeout",
                "polling_error",
            ],
        },
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "meta": {"type": ["object", "null"]},
                    "request": {"type": ["object", "null"]},
                    "run_id": {"type": ["string", "null"]},
                    "outcome": {
                        "type": "string",
                        "enum": [
                            "COMPLETED",
                            "FAILED",
                            "CANCELLED",
                            "RUN_CREATION_FAILED",
                            "WAIT_TIMEOUT",
                            "POLLING_ERROR",
                        ],
                    },
                    "run_status": {"type": ["string", "null"]},
                    "result": {},
                    "error": {"type": ["object", "null"]},
                    "duration_seconds": {"type": "number"},
                },
                "required": [
                    "id",
                    "meta",
                    "request",
                    "run_id",
                    "outcome",
                    "run_status",
                    "result",
                    "error",
                    "duration_seconds",
                ],
            },
        },
    },
    "required": ["job", "summary", "results"],
}


FANOUT_EXAMPLE: Dict[str, Any] = {
    "name": "multi-site-checks",
    "description": "Generic concurrent TinyFish task plan.",
    "request_defaults": {
        "browser_profile": "lite",
        "api_integration": "openclaw",
    },
    "tasks": [
        {
            "id": "site-a",
            "meta": {"site": "site-a", "kind": "lookup"},
            "request": {
                "url": "https://example.com/a",
                "goal": "Return JSON only with {\"title\":\"...\",\"price\":\"...\"}",
            },
        },
        {
            "id": "site-b",
            "meta": {"site": "site-b", "kind": "lookup"},
            "request": {
                "url": "https://example.com/b",
                "goal": "Return JSON only with {\"title\":\"...\",\"price\":\"...\"}",
            },
        },
    ],
}


def normalize_result_value(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def normalize_fanout_definition(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, list):
        raw = {"tasks": raw}
    if not isinstance(raw, dict):
        raise CliError(
            "Fanout input must be a JSON object or a JSON array of task objects",
            code="INVALID_FANOUT",
            details={"input_type": type(raw).__name__},
        )
    validate_fanout_definition(raw)
    normalized = deepcopy(raw)
    request_defaults = dict(normalized.get("request_defaults") or {})

    for task in normalized["tasks"]:
        merged_request = dict(request_defaults)
        merged_request.update(task["request"])
        task["request"] = merged_request

    normalized.setdefault("name", None)
    normalized.setdefault("description", None)
    normalized.setdefault("request_defaults", request_defaults)
    return normalized


def validate_fanout_definition(definition: Dict[str, Any]) -> None:
    tasks = definition.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise CliError(
            "Fanout definition must include a non-empty tasks array",
            code="INVALID_FANOUT",
        )

    request_defaults = definition.get("request_defaults")
    if request_defaults is not None and not isinstance(request_defaults, dict):
        raise CliError(
            "request_defaults must be an object",
            code="INVALID_FANOUT",
        )

    seen_ids = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise CliError("Each fanout task must be an object", code="INVALID_FANOUT")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise CliError("Each fanout task must have a non-empty string id", code="INVALID_FANOUT")
        if task_id in seen_ids:
            raise CliError(
                f"Duplicate fanout task id: {task_id}",
                code="INVALID_FANOUT",
            )
        seen_ids.add(task_id)

        meta = task.get("meta")
        if meta is not None and not isinstance(meta, dict):
            raise CliError(
                f"Fanout task {task_id} meta must be an object if provided",
                code="INVALID_FANOUT",
            )

        request = task.get("request")
        if not isinstance(request, dict):
            raise CliError(
                f"Fanout task {task_id} must include a request object",
                code="INVALID_FANOUT",
            )
        if not request.get("url") or not request.get("goal"):
            raise CliError(
                f"Fanout task {task_id} request must include url and goal",
                code="INVALID_FANOUT",
                details={"task_id": task_id},
            )


def get_fanout_schema(kind: str) -> Dict[str, Any]:
    if kind == "input":
        return FANOUT_INPUT_SCHEMA
    if kind == "output":
        return FANOUT_OUTPUT_SCHEMA
    if kind == "example":
        return FANOUT_EXAMPLE
    raise CliError(
        f"Unknown fanout schema kind: {kind}",
        code="INVALID_INPUT",
        details={"allowed": ["input", "output", "example"]},
    )


def select_tasks(definition: Dict[str, Any], task_ids: Optional[List[str]]) -> List[Dict[str, Any]]:
    tasks = definition["tasks"]
    if not task_ids:
        return tasks
    wanted = set(task_ids)
    selected = [task for task in tasks if task["id"] in wanted]
    if not selected:
        raise CliError(
            "No matching fanout tasks found",
            code="UNKNOWN_TASK",
            details={"requested": task_ids},
        )
    return selected


def summarize_outcomes(results: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {
        "total": len(results),
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "run_creation_failed": 0,
        "wait_timeout": 0,
        "polling_error": 0,
    }
    mapping = {
        "COMPLETED": "completed",
        "FAILED": "failed",
        "CANCELLED": "cancelled",
        "RUN_CREATION_FAILED": "run_creation_failed",
        "WAIT_TIMEOUT": "wait_timeout",
        "POLLING_ERROR": "polling_error",
    }
    for result in results:
        key = mapping.get(result["outcome"])
        if key is not None:
            summary[key] += 1
    return summary


def run_fanout(
    client: TinyFishClient,
    definition: Dict[str, Any],
    *,
    task_ids: Optional[List[str]],
    max_concurrency: int,
    interval: float,
    wait_timeout: float,
    fail_fast: bool,
    include_requests: bool,
    include_responses: bool,
) -> Tuple[Dict[str, Any], int]:
    if max_concurrency < 1:
        raise CliError("max_concurrency must be at least 1", code="INVALID_INPUT")

    selected_tasks = select_tasks(definition, task_ids)
    task_order = {task["id"]: index for index, task in enumerate(selected_tasks)}
    pending: Deque[Dict[str, Any]] = deque(selected_tasks)
    active: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []
    stop_starting = False
    started_at = datetime.now(timezone.utc).isoformat()

    while pending or active:
        while pending and len(active) < max_concurrency and not stop_starting:
            task = pending.popleft()
            task_record: Dict[str, Any] = {
                "id": task["id"],
                "meta": task.get("meta"),
                "request": task["request"] if include_requests else None,
                "run_id": None,
                "outcome": None,
                "run_status": None,
                "result": None,
                "error": None,
                "duration_seconds": 0.0,
            }
            task_started = time.monotonic()
            try:
                created = client.request_json("POST", "/v1/automation/run-async", payload=task["request"])
                if created.get("error"):
                    raise CliError(
                        created["error"].get("message", "TinyFish async run creation failed"),
                        code=created["error"].get("code", "RUN_CREATION_FAILED"),
                        details=created,
                    )
                task_record["run_id"] = created.get("run_id")
                active[task["id"]] = {
                    "task": task,
                    "task_record": task_record,
                    "started_monotonic": task_started,
                    "deadline": task_started + wait_timeout,
                    "poll_errors": 0,
                }
            except CliError as exc:
                task_record["outcome"] = "RUN_CREATION_FAILED"
                task_record["error"] = exc.to_payload()["error"]
                task_record["duration_seconds"] = round(time.monotonic() - task_started, 3)
                results.append(task_record)
                if fail_fast:
                    stop_starting = True

        if not active:
            continue

        completed_ids: List[str] = []
        now = time.monotonic()

        for task_id, state in list(active.items()):
            task_record = state["task_record"]
            run_id = task_record["run_id"]
            if now >= state["deadline"]:
                task_record["outcome"] = "WAIT_TIMEOUT"
                task_record["error"] = {
                    "code": "WAIT_TIMEOUT",
                    "message": f"Timed out waiting for run {run_id}",
                }
                task_record["duration_seconds"] = round(now - state["started_monotonic"], 3)
                completed_ids.append(task_id)
                if fail_fast:
                    stop_starting = True
                continue

            try:
                response = client.request_json("GET", f"/v1/runs/{run_id}")
            except CliError as exc:
                state["poll_errors"] += 1
                if state["poll_errors"] >= 3:
                    task_record["outcome"] = "POLLING_ERROR"
                    task_record["error"] = exc.to_payload()["error"]
                    task_record["duration_seconds"] = round(time.monotonic() - state["started_monotonic"], 3)
                    completed_ids.append(task_id)
                    if fail_fast:
                        stop_starting = True
                continue

            status = response.get("status")
            task_record["run_status"] = status
            if status not in {"COMPLETED", "FAILED", "CANCELLED"}:
                continue

            task_record["outcome"] = status
            task_record["result"] = normalize_result_value(response.get("result"))
            task_record["error"] = response.get("error")
            task_record["duration_seconds"] = round(time.monotonic() - state["started_monotonic"], 3)
            if include_responses:
                task_record["run_response"] = response
            completed_ids.append(task_id)
            if fail_fast and status != "COMPLETED":
                stop_starting = True

        for task_id in completed_ids:
            results.append(active.pop(task_id)["task_record"])

        if active:
            time.sleep(interval)

    results.sort(key=lambda item: task_order.get(item["id"], len(task_order)))
    summary = summarize_outcomes(results)
    payload = {
        "job": {
            "name": definition.get("name"),
            "description": definition.get("description"),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "max_concurrency": max_concurrency,
            "interval_seconds": interval,
            "wait_timeout_seconds": wait_timeout,
            "fail_fast": fail_fast,
            "requested_tasks": len(selected_tasks),
            "executed_task_ids": [result["id"] for result in results],
        },
        "summary": summary,
        "results": results,
    }
    exit_code = 0 if summary["failed"] == 0 and summary["cancelled"] == 0 and summary["run_creation_failed"] == 0 and summary["wait_timeout"] == 0 and summary["polling_error"] == 0 else 1
    return payload, exit_code
