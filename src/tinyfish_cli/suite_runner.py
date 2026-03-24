from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tinyfish_cli.builtin_suites import BUILTIN_SUITES
from tinyfish_cli.client import TinyFishClient
from tinyfish_cli.errors import CliError
from tinyfish_cli.fanout import run_fanout
from tinyfish_cli.run_ops import poll_run_until_terminal


def list_builtin_suites() -> List[Dict[str, Any]]:
    suites = []
    for suite in BUILTIN_SUITES.values():
        suites.append(
            {
                "name": suite["name"],
                "description": suite.get("description"),
                "scenario_count": len(suite.get("scenarios", [])),
                "scenario_ids": [scenario["id"] for scenario in suite.get("scenarios", [])],
            }
        )
    return suites


def load_suite(*, suite_name: Optional[str], suite_file: Optional[str]) -> Dict[str, Any]:
    if suite_name and suite_file:
        raise CliError("Pass either a built-in suite name or --file, not both", code="INVALID_INPUT")

    if suite_file:
        raw = json.loads(Path(suite_file).expanduser().read_text(encoding="utf-8"))
        validate_suite_definition(raw, source=suite_file)
        return raw

    if suite_name is None:
        raise CliError("A suite name or --file is required", code="INVALID_INPUT")

    suite = BUILTIN_SUITES.get(suite_name)
    if suite is None:
        raise CliError(
            f"Unknown built-in suite: {suite_name}",
            code="UNKNOWN_SUITE",
            details={"available_suites": sorted(BUILTIN_SUITES)},
        )
    return deepcopy(suite)


def validate_suite_definition(suite: Dict[str, Any], *, source: str) -> None:
    if not isinstance(suite, dict):
        raise CliError("Suite definition must be a JSON object", code="INVALID_SUITE", details={"source": source})

    scenarios = suite.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise CliError(
            "Suite definition must include a non-empty scenarios array",
            code="INVALID_SUITE",
            details={"source": source},
        )

    seen_ids = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise CliError("Each scenario must be a JSON object", code="INVALID_SUITE", details={"source": source})
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise CliError("Each scenario must have a non-empty string id", code="INVALID_SUITE", details={"source": source})
        if scenario_id in seen_ids:
            raise CliError(
                f"Duplicate scenario id: {scenario_id}",
                code="INVALID_SUITE",
                details={"source": source},
            )
        seen_ids.add(scenario_id)

        request = scenario.get("request")
        if not isinstance(request, dict):
            raise CliError(
                f"Scenario {scenario_id} must include a request object",
                code="INVALID_SUITE",
                details={"source": source},
            )
        if not request.get("url") or not request.get("goal"):
            raise CliError(
                f"Scenario {scenario_id} request must include url and goal",
                code="INVALID_SUITE",
                details={"source": source},
            )
        assertions = scenario.get("assertions", [])
        if not isinstance(assertions, list):
            raise CliError(
                f"Scenario {scenario_id} assertions must be an array",
                code="INVALID_SUITE",
                details={"source": source},
            )


def normalize_run_response(run_response: Dict[str, Any]) -> Dict[str, Any]:
    normalized = deepcopy(run_response)
    result = normalized.get("result")
    if isinstance(result, str):
        text = result.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                normalized["result"] = json.loads(text)
            except json.JSONDecodeError:
                pass
    return normalized


def resolve_path(data: Any, path: str) -> Any:
    current = data
    for raw_part in path.split("."):
        part = raw_part.strip()
        if part == "":
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise KeyError(f"Expected integer list index for path segment {part!r}") from exc
            current = current[index]
            continue
        if not isinstance(current, dict):
            raise KeyError(f"Cannot resolve segment {part!r} against non-object value")
        current = current[part]
    return current


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    return "string"


def evaluate_assertion(run_response: Dict[str, Any], assertion: Dict[str, Any]) -> Optional[str]:
    assertion_type = assertion.get("type")
    path = assertion.get("path", "")

    try:
        value = resolve_path(run_response, path) if path else run_response
    except (KeyError, IndexError) as exc:
        return f"{assertion_type}: path {path!r} was not found ({exc})"

    if assertion_type == "equals":
        expected = assertion.get("value")
        if value != expected:
            return f"equals: expected {path!r} to equal {expected!r}, got {value!r}"
        return None

    if assertion_type == "truthy":
        if not value:
            return f"truthy: expected {path!r} to be truthy, got {value!r}"
        return None

    if assertion_type == "contains":
        expected = assertion.get("value")
        if isinstance(value, str):
            if str(expected) not in value:
                return f"contains: expected {path!r} to contain {expected!r}, got {value!r}"
            return None
        if isinstance(value, list):
            if expected not in value:
                return f"contains: expected {path!r} to contain {expected!r}, got {value!r}"
            return None
        return f"contains: unsupported value type at {path!r}: {type_name(value)}"

    if assertion_type == "contains_all":
        expected_values = assertion.get("value", [])
        if not isinstance(value, list):
            return f"contains_all: expected {path!r} to be an array, got {type_name(value)}"
        missing = [item for item in expected_values if item not in value]
        if missing:
            return f"contains_all: missing {missing!r} from {path!r}, got {value!r}"
        return None

    if assertion_type == "min_items":
        minimum = assertion.get("value")
        if not isinstance(value, list):
            return f"min_items: expected {path!r} to be an array, got {type_name(value)}"
        if len(value) < int(minimum):
            return f"min_items: expected at least {minimum} items at {path!r}, got {len(value)}"
        return None

    if assertion_type == "type":
        expected = assertion.get("value")
        actual = type_name(value)
        if actual != expected:
            return f"type: expected {path!r} to be {expected!r}, got {actual!r}"
        return None

    if assertion_type == "all_items_have_keys":
        keys = assertion.get("keys", [])
        if not isinstance(value, list):
            return f"all_items_have_keys: expected {path!r} to be an array, got {type_name(value)}"
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                return f"all_items_have_keys: item {index} at {path!r} is not an object"
            missing = [key for key in keys if key not in item]
            if missing:
                return f"all_items_have_keys: item {index} at {path!r} is missing keys {missing!r}"
        return None

    return f"Unknown assertion type: {assertion_type!r}"


def validate_run_response(run_response: Dict[str, Any], assertions: Iterable[Dict[str, Any]]) -> List[str]:
    normalized = normalize_run_response(run_response)
    failures = []
    for assertion in assertions:
        failure = evaluate_assertion(normalized, assertion)
        if failure:
            failures.append(failure)
    return failures


def run_suite(
    client: TinyFishClient,
    suite: Dict[str, Any],
    *,
    scenario_ids: Optional[List[str]] = None,
    interval: float,
    wait_timeout: float,
    fail_fast: bool,
    include_responses: bool,
) -> Tuple[Dict[str, Any], int]:
    started_at = datetime.now(timezone.utc).isoformat()
    selected = suite["scenarios"]
    if scenario_ids:
        selected = [scenario for scenario in selected if scenario["id"] in set(scenario_ids)]
        if not selected:
            raise CliError(
                "No matching scenarios found in the selected suite",
                code="UNKNOWN_SCENARIO",
                details={"requested": scenario_ids},
            )

    results = []
    passed = 0
    failed = 0

    for scenario in selected:
        scenario_started = time.monotonic()
        scenario_result: Dict[str, Any] = {
            "id": scenario["id"],
            "description": scenario.get("description"),
            "request": scenario["request"],
            "passed": False,
            "run_id": None,
            "run_status": None,
            "validation_errors": [],
            "error": None,
        }
        try:
            created = client.request_json("POST", "/v1/automation/run-async", payload=scenario["request"])
            if created.get("error"):
                raise CliError(
                    created["error"].get("message", "TinyFish async run creation failed"),
                    code=created["error"].get("code", "RUN_CREATION_FAILED"),
                    details=created,
                )
            run_id = created.get("run_id")
            scenario_result["run_id"] = run_id
            final_response = poll_run_until_terminal(
                client,
                str(run_id),
                interval=interval,
                wait_timeout=wait_timeout,
            )
            scenario_result["run_status"] = final_response.get("status")
            failures = validate_run_response(final_response, scenario.get("assertions", []))
            scenario_result["validation_errors"] = failures
            scenario_result["passed"] = not failures
            if include_responses or failures:
                scenario_result["run_response"] = final_response
        except CliError as exc:
            scenario_result["error"] = exc.to_payload()["error"]
        finally:
            scenario_result["duration_seconds"] = round(time.monotonic() - scenario_started, 3)

        if scenario_result["passed"]:
            passed += 1
        else:
            failed += 1

        results.append(scenario_result)
        if failed and fail_fast:
            break

    summary = {
        "suite": {
            "name": suite.get("name"),
            "description": suite.get("description"),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "selected_scenarios": [scenario["id"] for scenario in selected[: len(results)]],
        },
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
        },
        "results": results,
    }
    return summary, 0 if failed == 0 else 1


def build_suite_fanout_definition(
    suite: Dict[str, Any],
    *,
    scenario_ids: Optional[List[str]],
    duplicates: int,
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    if duplicates < 1:
        raise CliError("fanout duplicates must be at least 1", code="INVALID_INPUT")

    selected = suite["scenarios"]
    if scenario_ids:
        selected = [scenario for scenario in selected if scenario["id"] in set(scenario_ids)]
        if not selected:
            raise CliError(
                "No matching scenarios found in the selected suite",
                code="UNKNOWN_SCENARIO",
                details={"requested": scenario_ids},
            )

    scenario_lookup = {scenario["id"]: scenario for scenario in selected}
    tasks = []
    for scenario in selected:
        for replica in range(1, duplicates + 1):
            tasks.append(
                {
                    "id": f"{scenario['id']}--{replica}",
                    "meta": {
                        "suite_name": suite.get("name"),
                        "scenario_id": scenario["id"],
                        "replica": replica,
                    },
                    "request": deepcopy(scenario["request"]),
                }
            )

    definition = {
        "name": f"{suite.get('name')}-fanout" if suite.get("name") else "suite-fanout",
        "description": f"Fanout execution for suite {suite.get('name')}",
        "tasks": tasks,
    }
    return definition, scenario_lookup, selected


def run_suite_fanout(
    client: TinyFishClient,
    suite: Dict[str, Any],
    *,
    scenario_ids: Optional[List[str]],
    duplicates: int,
    max_concurrency: int,
    interval: float,
    wait_timeout: float,
    fail_fast: bool,
    include_responses: bool,
) -> Tuple[Dict[str, Any], int]:
    definition, scenario_lookup, selected = build_suite_fanout_definition(
        suite,
        scenario_ids=scenario_ids,
        duplicates=duplicates,
    )
    fanout_payload, _ = run_fanout(
        client,
        definition,
        task_ids=None,
        max_concurrency=max_concurrency,
        interval=interval,
        wait_timeout=wait_timeout,
        fail_fast=fail_fast,
        include_requests=False,
        include_responses=True,
    )

    results = []
    passed = 0
    failed = 0

    for fanout_result in fanout_payload["results"]:
        scenario_id = fanout_result.get("meta", {}).get("scenario_id")
        scenario = scenario_lookup[scenario_id]
        run_response = fanout_result.get("run_response")
        validation_errors = []

        if run_response is not None:
            validation_errors = validate_run_response(run_response, scenario.get("assertions", []))
        elif fanout_result["outcome"] != "RUN_CREATION_FAILED":
            validation_errors = [f"Missing run response for outcome {fanout_result['outcome']}"]

        result: Dict[str, Any] = {
            "id": fanout_result["id"],
            "scenario_id": scenario_id,
            "replica": fanout_result.get("meta", {}).get("replica"),
            "description": scenario.get("description"),
            "passed": not validation_errors and fanout_result.get("error") is None,
            "executor_outcome": fanout_result["outcome"],
            "run_id": fanout_result["run_id"],
            "run_status": fanout_result["run_status"],
            "validation_errors": validation_errors,
            "error": fanout_result.get("error"),
            "duration_seconds": fanout_result["duration_seconds"],
        }
        if include_responses or validation_errors:
            result["run_response"] = run_response

        if result["passed"]:
            passed += 1
        else:
            failed += 1

        results.append(result)

    summary = {
        "suite": {
            "name": suite.get("name"),
            "description": suite.get("description"),
            "started_at": fanout_payload["job"]["started_at"],
            "finished_at": fanout_payload["job"]["finished_at"],
            "selected_scenarios": [scenario["id"] for scenario in selected],
            "mode": "fanout",
            "fanout_duplicates": duplicates,
            "fanout_max_concurrency": max_concurrency,
        },
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
        },
        "results": results,
        "fanout": {
            "job": fanout_payload["job"],
            "summary": fanout_payload["summary"],
        },
    }
    return summary, 0 if failed == 0 else 1
