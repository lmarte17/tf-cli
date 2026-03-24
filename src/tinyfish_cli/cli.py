from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from tinyfish_cli import __version__
from tinyfish_cli.client import TinyFishClient
from tinyfish_cli.config import (
    API_KEYS_URL,
    clear_api_key,
    expand_config_path,
    load_config,
    open_api_keys_page,
    preview_api_key,
    prompt_for_api_key,
    resolve_api_key,
    save_api_key,
)
from tinyfish_cli.errors import CliError
from tinyfish_cli.fanout import get_fanout_schema, normalize_fanout_definition, run_fanout
from tinyfish_cli.formatting import emit_json, emit_pretty_sse_event
from tinyfish_cli.run_ops import poll_run_until_terminal
from tinyfish_cli.suite_runner import list_builtin_suites, load_suite, run_suite, run_suite_fanout

RUN_STATUSES = ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
SORT_DIRECTIONS = ["asc", "desc"]
BROWSER_PROFILES = ["lite", "stealth"]
PROXY_COUNTRIES = ["US", "GB", "CA", "DE", "FR", "JP", "AU"]
BROWSER_USAGE_STATUSES = ["running", "ended"]


def normalize_argv(argv: List[str]) -> List[str]:
    if argv[:2] != ["agent", "run"]:
        return argv

    tail = argv[2:]
    if not tail or tail[0].startswith("-"):
        return ["run"] + tail

    mapping = {
        "list": ["runs", "list"],
        "get": ["runs", "get"],
        "get-many": ["runs", "get-many"],
        "cancel": ["runs", "cancel"],
        "cancel-many": ["runs", "cancel-many"],
        "wait": ["runs", "wait"],
        "async": ["run-async"],
        "sse": ["run-sse"],
        "batch": ["run-batch"],
    }
    if tail[0] in mapping:
        return mapping[tail[0]] + tail[1:]
    return ["run"] + tail


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default="https://agent.tinyfish.ai", help="TinyFish API base URL")
    common.add_argument("--api-key", help="Explicit TinyFish API key override")
    common.add_argument("--config", help="Path to TinyFish config file")
    common.add_argument("--timeout", type=float, default=300.0, help="Request timeout in seconds")
    common.add_argument("--pretty", action="store_true", help="Pretty-print output")

    parser = argparse.ArgumentParser(prog="tinyfish", parents=[common])
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    auth = subparsers.add_parser("auth", parents=[common], help="Manage TinyFish API auth")
    auth_sub = auth.add_subparsers(dest="auth_command")

    auth_login = auth_sub.add_parser("login", parents=[common], help="Open the TinyFish API key page and save a key")
    auth_login.add_argument("api_key", nargs="?", help="Optional API key to save without prompting")
    auth_login.set_defaults(handler=handle_auth_login)

    auth_set = auth_sub.add_parser("set", parents=[common], help="Save a TinyFish API key")
    auth_set.add_argument("api_key", nargs="?", help="Optional API key to save; otherwise read stdin or prompt")
    auth_set.set_defaults(handler=handle_auth_set)

    auth_status = auth_sub.add_parser("status", parents=[common], help="Show TinyFish auth status")
    auth_status.set_defaults(handler=handle_auth_status)

    auth_logout = auth_sub.add_parser("logout", parents=[common], help="Remove the saved TinyFish API key")
    auth_logout.set_defaults(handler=handle_auth_logout)

    run = subparsers.add_parser("run", parents=[common], help="Run a synchronous TinyFish automation")
    add_single_run_options(run)
    run.set_defaults(handler=handle_run)

    run_async = subparsers.add_parser("run-async", parents=[common], help="Start an async TinyFish automation")
    add_single_run_options(run_async)
    run_async.set_defaults(handler=handle_run_async)

    run_sse = subparsers.add_parser("run-sse", parents=[common], help="Run an SSE-streamed TinyFish automation")
    add_single_run_options(run_sse)
    run_sse.add_argument("--show-heartbeats", action="store_true", help="Show HEARTBEAT events in --pretty mode")
    run_sse.set_defaults(handler=handle_run_sse)

    run_batch = subparsers.add_parser("run-batch", parents=[common], help="Start multiple async automations")
    run_batch.add_argument("--input", required=True, help="JSON object with runs or a JSON array of runs; use - for stdin")
    run_batch.set_defaults(handler=handle_run_batch)

    runs = subparsers.add_parser("runs", parents=[common], help="Inspect and manage automation runs")
    runs_sub = runs.add_subparsers(dest="runs_command")

    runs_list = runs_sub.add_parser("list", parents=[common], help="List and search runs")
    runs_list.add_argument("--status", choices=RUN_STATUSES)
    runs_list.add_argument("--goal")
    runs_list.add_argument("--created-after")
    runs_list.add_argument("--created-before")
    runs_list.add_argument("--sort-direction", choices=SORT_DIRECTIONS)
    runs_list.add_argument("--cursor")
    runs_list.add_argument("--limit", type=int)
    runs_list.set_defaults(handler=handle_runs_list)

    runs_get = runs_sub.add_parser("get", parents=[common], help="Get a single run")
    runs_get.add_argument("run_id")
    runs_get.set_defaults(handler=handle_runs_get)

    runs_get_many = runs_sub.add_parser("get-many", parents=[common], help="Get multiple runs")
    runs_get_many.add_argument("run_ids", nargs="*")
    runs_get_many.add_argument("--input", help="JSON object with run_ids or JSON array of run_ids; use - for stdin")
    runs_get_many.set_defaults(handler=handle_runs_get_many)

    runs_wait = runs_sub.add_parser("wait", parents=[common], help="Poll a run until it reaches a terminal status")
    runs_wait.add_argument("run_id")
    runs_wait.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    runs_wait.add_argument("--wait-timeout", type=float, default=300.0, help="Maximum wait time in seconds")
    runs_wait.set_defaults(handler=handle_runs_wait)

    runs_cancel = runs_sub.add_parser("cancel", parents=[common], help="Cancel a single run")
    runs_cancel.add_argument("run_id")
    runs_cancel.set_defaults(handler=handle_runs_cancel)

    runs_cancel_many = runs_sub.add_parser("cancel-many", parents=[common], help="Cancel multiple runs")
    runs_cancel_many.add_argument("run_ids", nargs="*")
    runs_cancel_many.add_argument("--input", help="JSON object with run_ids or JSON array of run_ids; use - for stdin")
    runs_cancel_many.set_defaults(handler=handle_runs_cancel_many)

    browser = subparsers.add_parser("browser", parents=[common], help="Remote browser session commands")
    browser_sub = browser.add_subparsers(dest="browser_command")

    browser_create = browser_sub.add_parser("create", parents=[common], help="Create a remote browser session")
    browser_create.set_defaults(handler=handle_browser_create)

    browser_usage = browser_sub.add_parser("usage", parents=[common], help="List browser session usage")
    browser_usage.add_argument("--session-id")
    browser_usage.add_argument("--start-after")
    browser_usage.add_argument("--end-before")
    browser_usage.add_argument("--status", choices=BROWSER_USAGE_STATUSES)
    browser_usage.add_argument("--limit", type=int)
    browser_usage.add_argument("--page", type=int)
    browser_usage.set_defaults(handler=handle_browser_usage)

    fanout = subparsers.add_parser("fanout", parents=[common], help="Run multiple TinyFish tasks with bounded concurrency")
    fanout_sub = fanout.add_subparsers(dest="fanout_command")

    fanout_schema = fanout_sub.add_parser("schema", parents=[common], help="Print fanout input/output schemas or example plans")
    fanout_schema.add_argument("kind", choices=["input", "output", "example"], nargs="?", default="input")
    fanout_schema.set_defaults(handler=handle_fanout_schema)

    fanout_validate = fanout_sub.add_parser("validate", parents=[common], help="Validate and normalize a fanout task plan")
    fanout_validate.add_argument("--input", required=True, help="Fanout JSON file or - for stdin")
    fanout_validate.add_argument("--task", dest="task_ids", action="append", help="Specific task ID to include; may be repeated")
    fanout_validate.set_defaults(handler=handle_fanout_validate)

    fanout_run = fanout_sub.add_parser("run", parents=[common], help="Execute a fanout task plan with bounded concurrency")
    fanout_run.add_argument("--input", required=True, help="Fanout JSON file or - for stdin")
    fanout_run.add_argument("--task", dest="task_ids", action="append", help="Specific task ID to include; may be repeated")
    fanout_run.add_argument("--max-concurrency", type=int, default=5, help="Maximum number of active TinyFish runs")
    fanout_run.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    fanout_run.add_argument("--wait-timeout", type=float, default=300.0, help="Maximum wait time per task in seconds")
    fanout_run.add_argument("--fail-fast", action="store_true", help="Stop starting new tasks after the first failure")
    fanout_run.add_argument(
        "--include-requests",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include normalized task requests in output",
    )
    fanout_run.add_argument(
        "--include-responses",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include full TinyFish run responses in output",
    )
    fanout_run.set_defaults(handler=handle_fanout_run)

    suite = subparsers.add_parser("suite", parents=[common], help="Run built-in or custom TinyFish integration suites")
    suite_sub = suite.add_subparsers(dest="suite_command")

    suite_list = suite_sub.add_parser("list", parents=[common], help="List built-in suites")
    suite_list.set_defaults(handler=handle_suite_list)

    suite_show = suite_sub.add_parser("show", parents=[common], help="Show a suite definition")
    suite_show.add_argument("suite_name", nargs="?")
    suite_show.add_argument("--file", help="Path to a custom suite JSON file")
    suite_show.set_defaults(handler=handle_suite_show)

    suite_run = suite_sub.add_parser("run", parents=[common], help="Run a built-in or custom suite")
    suite_run.add_argument("suite_name", nargs="?")
    suite_run.add_argument("--file", help="Path to a custom suite JSON file")
    suite_run.add_argument(
        "--scenario",
        dest="scenario_ids",
        action="append",
        help="Specific scenario ID to run; may be repeated",
    )
    suite_run.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    suite_run.add_argument("--wait-timeout", type=float, default=300.0, help="Maximum wait time per scenario in seconds")
    suite_run.add_argument("--fail-fast", action="store_true", help="Stop after the first failed scenario")
    suite_run.add_argument("--fanout", action="store_true", help="Run duplicated suite scenarios concurrently through the fanout executor")
    suite_run.add_argument("--fanout-duplicates", type=int, default=2, help="How many duplicates of each selected scenario to run in fanout mode")
    suite_run.add_argument("--fanout-max-concurrency", type=int, default=5, help="Maximum active fanout runs when --fanout is used")
    suite_run.add_argument(
        "--include-responses",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include full run responses in suite output",
    )
    suite_run.set_defaults(handler=handle_suite_run)

    return parser


def add_single_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", help="JSON object input file or - for stdin")
    parser.add_argument("--url", help="Target URL")
    parser.add_argument("--goal", help="Automation goal in natural language")
    parser.add_argument("--browser-profile", choices=BROWSER_PROFILES)
    parser.add_argument(
        "--proxy-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable proxy usage",
    )
    parser.add_argument("--proxy-country", choices=PROXY_COUNTRIES, help="Proxy country code")
    parser.add_argument("--api-integration", help="Integration label, for example openclaw")
    parser.add_argument(
        "--enable-agent-memory",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable TinyFish agent memory",
    )
    parser.add_argument(
        "--use-vault",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable TinyFish vault credentials",
    )
    parser.add_argument(
        "--credential-item-id",
        dest="credential_item_ids",
        action="append",
        default=None,
        help="Vault credential item ID; may be repeated",
    )


def read_json_input(path: str) -> Any:
    if path == "-":
        text = sys.stdin.read()
    else:
        text = Path(path).expanduser().read_text(encoding="utf-8")
    try:
        import json

        return json.loads(text)
    except Exception as exc:
        raise CliError(
            "Invalid JSON input",
            code="INVALID_JSON",
            details={"input": path, "error": str(exc)},
        ) from exc


def build_single_run_payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if args.input:
        raw = read_json_input(args.input)
        if not isinstance(raw, dict):
            raise CliError(
                "Single-run input must be a JSON object",
                code="INVALID_INPUT",
                details={"input_type": type(raw).__name__},
            )
        payload.update(raw)

    if args.url:
        payload["url"] = args.url
    if args.goal:
        payload["goal"] = args.goal
    if args.browser_profile:
        payload["browser_profile"] = args.browser_profile
    if args.api_integration:
        payload["api_integration"] = args.api_integration

    if args.proxy_enabled is not None or args.proxy_country is not None:
        proxy_config = dict(payload.get("proxy_config") or {})
        if args.proxy_enabled is not None:
            proxy_config["enabled"] = args.proxy_enabled
        elif "enabled" not in proxy_config and args.proxy_country is not None:
            proxy_config["enabled"] = True
        if args.proxy_country is not None:
            proxy_config["country_code"] = args.proxy_country
        payload["proxy_config"] = proxy_config

    if args.enable_agent_memory is not None:
        feature_flags = dict(payload.get("feature_flags") or {})
        feature_flags["enable_agent_memory"] = args.enable_agent_memory
        payload["feature_flags"] = feature_flags

    if args.use_vault is not None:
        payload["use_vault"] = args.use_vault
    if args.credential_item_ids:
        payload["credential_item_ids"] = args.credential_item_ids
        if "use_vault" not in payload:
            payload["use_vault"] = True

    missing = [field for field in ("url", "goal") if not payload.get(field)]
    if missing:
        raise CliError(
            "Missing required TinyFish automation fields",
            code="INVALID_INPUT",
            details={"missing": missing},
        )
    return payload


def build_batch_run_payload(args: argparse.Namespace) -> Dict[str, Any]:
    raw = read_json_input(args.input)
    if isinstance(raw, list):
        return {"runs": raw}
    if isinstance(raw, dict) and isinstance(raw.get("runs"), list):
        return raw
    raise CliError(
        "Batch run input must be a JSON array or an object with a runs array",
        code="INVALID_INPUT",
    )


def resolve_run_ids(args: argparse.Namespace) -> List[str]:
    if args.run_ids:
        return args.run_ids
    if args.input:
        raw = read_json_input(args.input)
        if isinstance(raw, list):
            return [str(item) for item in raw]
        if isinstance(raw, dict) and isinstance(raw.get("run_ids"), list):
            return [str(item) for item in raw["run_ids"]]
    raise CliError("No run IDs provided", code="INVALID_INPUT")


def get_client(args: argparse.Namespace) -> TinyFishClient:
    config_path = expand_config_path(args.config)
    api_key, source = resolve_api_key(args.api_key, config_path)
    if not api_key:
        raise CliError(
            "TinyFish API key not found. Set TINYFISH_API_KEY or run tinyfish auth login.",
            code="MISSING_API_KEY",
            details={"source": source, "config_path": str(config_path)},
        )
    return TinyFishClient(base_url=args.base_url, api_key=api_key, timeout=args.timeout)


def handle_auth_login(args: argparse.Namespace) -> int:
    config_path = expand_config_path(args.config)
    opened = open_api_keys_page()
    api_key = prompt_for_api_key(args.api_key)
    if not api_key:
        raise CliError("No TinyFish API key provided", code="MISSING_API_KEY")
    save_api_key(config_path, api_key)
    emit_json(
        {
            "authenticated": True,
            "source": "config",
            "key_preview": preview_api_key(api_key),
            "config_path": str(config_path),
            "opened_browser": opened,
            "api_keys_url": API_KEYS_URL,
        },
        pretty=args.pretty,
    )
    return 0


def handle_auth_set(args: argparse.Namespace) -> int:
    config_path = expand_config_path(args.config)
    api_key = prompt_for_api_key(args.api_key)
    if not api_key:
        raise CliError("No TinyFish API key provided", code="MISSING_API_KEY")
    save_api_key(config_path, api_key)
    emit_json(
        {
            "authenticated": True,
            "source": "config",
            "key_preview": preview_api_key(api_key),
            "config_path": str(config_path),
        },
        pretty=args.pretty,
    )
    return 0


def handle_auth_status(args: argparse.Namespace) -> int:
    config_path = expand_config_path(args.config)
    api_key, source = resolve_api_key(args.api_key, config_path)
    payload = {
        "authenticated": bool(api_key),
        "source": source,
        "key_preview": preview_api_key(api_key),
        "config_path": str(config_path),
        "config_exists": config_path.exists(),
    }
    emit_json(payload, pretty=args.pretty)
    return 0 if api_key else 1


def handle_auth_logout(args: argparse.Namespace) -> int:
    config_path = expand_config_path(args.config)
    load_config(config_path)
    clear_api_key(config_path)
    emit_json(
        {"authenticated": False, "source": "none", "config_path": str(config_path)},
        pretty=args.pretty,
    )
    return 0


def handle_run(args: argparse.Namespace) -> int:
    client = get_client(args)
    payload = build_single_run_payload(args)
    response = client.request_json("POST", "/v1/automation/run", payload=payload, expected_statuses=(200, 500))
    return emit_terminal_run_response(response, pretty=args.pretty)


def handle_run_async(args: argparse.Namespace) -> int:
    client = get_client(args)
    payload = build_single_run_payload(args)
    response = client.request_json("POST", "/v1/automation/run-async", payload=payload)
    if response.get("error"):
        raise CliError(
            response["error"].get("message", "TinyFish async run creation failed"),
            code=response["error"].get("code", "RUN_CREATION_FAILED"),
            details=response,
        )
    emit_json(response, pretty=args.pretty)
    return 0


def handle_run_sse(args: argparse.Namespace) -> int:
    client = get_client(args)
    payload = build_single_run_payload(args)
    saw_complete = False
    last_event: Optional[Dict[str, Any]] = None

    for event in client.stream_sse("/v1/automation/run-sse", payload=payload):
        last_event = event if isinstance(event, dict) else None
        if isinstance(event, dict) and event.get("type") == "COMPLETE":
            saw_complete = True
        if args.pretty:
            emit_pretty_sse_event(event, show_heartbeats=args.show_heartbeats)
        else:
            emit_json(event)

    if not saw_complete:
        raise CliError(
            "TinyFish SSE stream ended before a COMPLETE event was received",
            code="INCOMPLETE_STREAM",
            details=last_event,
        )

    status = last_event.get("status") if isinstance(last_event, dict) else None
    if status in {"FAILED", "CANCELLED"}:
        raise CliError(
            f"TinyFish automation ended with status {status}",
            code=f"RUN_{status}",
            details=last_event,
        )
    return 0


def handle_run_batch(args: argparse.Namespace) -> int:
    client = get_client(args)
    payload = build_batch_run_payload(args)
    response = client.request_json("POST", "/v1/automation/run-batch", payload=payload)
    if response.get("error"):
        raise CliError(
            response["error"].get("message", "TinyFish batch run creation failed"),
            code=response["error"].get("code", "RUN_BATCH_FAILED"),
            details=response,
        )
    emit_json(response, pretty=args.pretty)
    return 0


def handle_runs_list(args: argparse.Namespace) -> int:
    client = get_client(args)
    response = client.request_json(
        "GET",
        "/v1/runs",
        query={
            "status": args.status,
            "goal": args.goal,
            "created_after": args.created_after,
            "created_before": args.created_before,
            "sort_direction": args.sort_direction,
            "cursor": args.cursor,
            "limit": args.limit,
        },
    )
    emit_json(response, pretty=args.pretty)
    return 0


def handle_runs_get(args: argparse.Namespace) -> int:
    client = get_client(args)
    response = client.request_json("GET", f"/v1/runs/{args.run_id}")
    emit_json(response, pretty=args.pretty)
    return 0


def handle_runs_get_many(args: argparse.Namespace) -> int:
    client = get_client(args)
    run_ids = resolve_run_ids(args)
    response = client.request_json("POST", "/v1/runs/batch", payload={"run_ids": run_ids})
    emit_json(response, pretty=args.pretty)
    return 0


def handle_runs_wait(args: argparse.Namespace) -> int:
    client = get_client(args)
    last_status = None

    def on_poll(response: Dict[str, Any]) -> None:
        nonlocal last_status
        status = response.get("status")
        if args.pretty and status != last_status:
            emit_json(
                {
                    "run_id": response.get("run_id"),
                    "status": status,
                    "started_at": response.get("started_at"),
                    "finished_at": response.get("finished_at"),
                },
                pretty=True,
            )
            last_status = status

    response = poll_run_until_terminal(
        client,
        args.run_id,
        interval=args.interval,
        wait_timeout=args.wait_timeout,
        on_poll=on_poll,
    )
    status = response.get("status")
    if status in {"FAILED", "CANCELLED"}:
        raise CliError(
            f"TinyFish run reached terminal status {status}",
            code=f"RUN_{status}",
            details=response,
        )
    emit_json(response, pretty=args.pretty)
    return 0


def handle_runs_cancel(args: argparse.Namespace) -> int:
    client = get_client(args)
    response = client.request_json("POST", f"/v1/runs/{args.run_id}/cancel")
    emit_json(response, pretty=args.pretty)
    return 0


def handle_runs_cancel_many(args: argparse.Namespace) -> int:
    client = get_client(args)
    run_ids = resolve_run_ids(args)
    response = client.request_json("POST", "/v1/runs/batch/cancel", payload={"run_ids": run_ids})
    emit_json(response, pretty=args.pretty)
    return 0


def handle_browser_create(args: argparse.Namespace) -> int:
    client = get_client(args)
    response = client.request_json("POST", "/v1/browser", expected_statuses=(201,))
    emit_json(response, pretty=args.pretty)
    return 0


def handle_browser_usage(args: argparse.Namespace) -> int:
    client = get_client(args)
    response = client.request_json(
        "GET",
        "/v1/browser/usage",
        query={
            "session_id": args.session_id,
            "start_after": args.start_after,
            "end_before": args.end_before,
            "status": args.status,
            "limit": args.limit,
            "page": args.page,
        },
    )
    emit_json(response, pretty=args.pretty)
    return 0


def handle_fanout_schema(args: argparse.Namespace) -> int:
    emit_json(
        {
            "kind": args.kind,
            "schema": get_fanout_schema(args.kind),
        },
        pretty=args.pretty,
    )
    return 0


def handle_fanout_validate(args: argparse.Namespace) -> int:
    normalized = normalize_fanout_definition(read_json_input(args.input))
    tasks = normalized["tasks"]
    if args.task_ids:
        wanted = set(args.task_ids)
        tasks = [task for task in tasks if task["id"] in wanted]
        if not tasks:
            raise CliError(
                "No matching fanout tasks found",
                code="UNKNOWN_TASK",
                details={"requested": args.task_ids},
            )
    emit_json(
        {
            "valid": True,
            "name": normalized.get("name"),
            "description": normalized.get("description"),
            "task_count": len(tasks),
            "task_ids": [task["id"] for task in tasks],
            "request_defaults": normalized.get("request_defaults"),
            "tasks": tasks,
        },
        pretty=args.pretty,
    )
    return 0


def handle_fanout_run(args: argparse.Namespace) -> int:
    client = get_client(args)
    normalized = normalize_fanout_definition(read_json_input(args.input))
    payload, exit_code = run_fanout(
        client,
        normalized,
        task_ids=args.task_ids,
        max_concurrency=args.max_concurrency,
        interval=args.interval,
        wait_timeout=args.wait_timeout,
        fail_fast=args.fail_fast,
        include_requests=args.include_requests,
        include_responses=args.include_responses,
    )
    emit_json(payload, pretty=args.pretty)
    return exit_code


def handle_suite_list(args: argparse.Namespace) -> int:
    emit_json({"suites": list_builtin_suites()}, pretty=args.pretty)
    return 0


def handle_suite_show(args: argparse.Namespace) -> int:
    suite = load_suite(suite_name=args.suite_name, suite_file=args.file)
    emit_json(suite, pretty=args.pretty)
    return 0


def handle_suite_run(args: argparse.Namespace) -> int:
    client = get_client(args)
    suite = load_suite(suite_name=args.suite_name, suite_file=args.file)
    if args.fanout:
        summary, exit_code = run_suite_fanout(
            client,
            suite,
            scenario_ids=args.scenario_ids,
            duplicates=args.fanout_duplicates,
            max_concurrency=args.fanout_max_concurrency,
            interval=args.interval,
            wait_timeout=args.wait_timeout,
            fail_fast=args.fail_fast,
            include_responses=args.include_responses,
        )
    else:
        summary, exit_code = run_suite(
            client,
            suite,
            scenario_ids=args.scenario_ids,
            interval=args.interval,
            wait_timeout=args.wait_timeout,
            fail_fast=args.fail_fast,
            include_responses=args.include_responses,
        )
    emit_json(summary, pretty=args.pretty)
    return exit_code


def emit_terminal_run_response(response: Dict[str, Any], *, pretty: bool) -> int:
    status = response.get("status")
    if status == "FAILED":
        error = response.get("error") or {}
        raise CliError(
            error.get("message", "TinyFish automation failed"),
            code="RUN_FAILED",
            details=response,
        )
    emit_json(response, pretty=pretty)
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    raw_args = list(argv if argv is not None else sys.argv[1:])
    parser = build_parser()
    args = parser.parse_args(normalize_argv(raw_args))

    if not hasattr(args, "handler"):
        parser.print_help(sys.stderr)
        return 1

    try:
        return int(args.handler(args))
    except CliError as exc:
        emit_json(exc.to_payload(), pretty=args.pretty, stream=sys.stderr)
        return exc.exit_code
