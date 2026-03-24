import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tinyfish_cli.fanout import FANOUT_EXAMPLE, get_fanout_schema, normalize_fanout_definition, run_fanout


class FakeClient:
    def __init__(self) -> None:
        self.created = []
        self.active_run_ids = set()
        self.max_active_seen = 0
        self.poll_count = {}

    def request_json(self, method, path, *, payload=None, query=None, expected_statuses=(200,)):
        if method == "POST" and path == "/v1/automation/run-async":
            run_id = f"run_{len(self.created) + 1}"
            self.created.append((run_id, payload["url"]))
            self.active_run_ids.add(run_id)
            self.max_active_seen = max(self.max_active_seen, len(self.active_run_ids))
            return {"run_id": run_id, "error": None}

        if method == "GET" and path.startswith("/v1/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            polls = self.poll_count.get(run_id, 0) + 1
            self.poll_count[run_id] = polls
            if polls >= 2:
                self.active_run_ids.discard(run_id)
                return {
                    "run_id": run_id,
                    "status": "COMPLETED",
                    "result": {"run_id": run_id},
                    "error": None,
                }
            return {
                "run_id": run_id,
                "status": "RUNNING",
                "result": None,
                "error": None,
            }

        raise AssertionError(f"Unexpected request: {method} {path}")


class FanoutTests(unittest.TestCase):
    def test_normalize_fanout_definition_merges_request_defaults(self) -> None:
        normalized = normalize_fanout_definition(FANOUT_EXAMPLE)
        first = normalized["tasks"][0]["request"]
        self.assertEqual(first["browser_profile"], "lite")
        self.assertEqual(first["api_integration"], "openclaw")

    def test_get_fanout_schema_example(self) -> None:
        schema = get_fanout_schema("example")
        self.assertEqual(schema["name"], "multi-site-checks")

    def test_run_fanout_respects_max_concurrency(self) -> None:
        definition = normalize_fanout_definition(
            {
                "tasks": [
                    {"id": "task-1", "request": {"url": "https://example.com/1", "goal": "one"}},
                    {"id": "task-2", "request": {"url": "https://example.com/2", "goal": "two"}},
                    {"id": "task-3", "request": {"url": "https://example.com/3", "goal": "three"}},
                ]
            }
        )
        client = FakeClient()
        payload, exit_code = run_fanout(
            client,
            definition,
            task_ids=None,
            max_concurrency=2,
            interval=0.0,
            wait_timeout=10.0,
            fail_fast=False,
            include_requests=False,
            include_responses=False,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["summary"]["completed"], 3)
        self.assertEqual(client.max_active_seen, 2)
