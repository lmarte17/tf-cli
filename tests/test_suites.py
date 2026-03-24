import sys
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tinyfish_cli.builtin_suites import BUILTIN_SUITES
from tinyfish_cli.suite_runner import (
    build_suite_fanout_definition,
    evaluate_assertion,
    list_builtin_suites,
    normalize_run_response,
    resolve_path,
    run_suite_fanout,
)


class SuiteHelpersTests(unittest.TestCase):
    def test_resolve_path_traverses_nested_objects(self) -> None:
        payload = {"result": {"items": [{"title": "Book A"}]}}
        self.assertEqual(resolve_path(payload, "result.items.0.title"), "Book A")

    def test_normalize_run_response_parses_json_string_result(self) -> None:
        response = {"result": '{"submitted": true, "confirmation_message": "Received!"}'}
        normalized = normalize_run_response(response)
        self.assertEqual(normalized["result"]["submitted"], True)

    def test_evaluate_assertion_contains_all(self) -> None:
        response = {"status": "COMPLETED", "result": {"pages_visited": [1, 2]}}
        failure = evaluate_assertion(response, {"type": "contains_all", "path": "result.pages_visited", "value": [1, 2]})
        self.assertIsNone(failure)

    def test_builtin_suite_is_listed(self) -> None:
        suites = list_builtin_suites()
        self.assertTrue(any(suite["name"] == "common-web" for suite in suites))

    def test_build_suite_fanout_definition_duplicates_scenarios(self) -> None:
        definition, scenario_lookup, selected = build_suite_fanout_definition(
            BUILTIN_SUITES["common-web"],
            scenario_ids=["cart-addition"],
            duplicates=2,
        )
        self.assertEqual([task["id"] for task in definition["tasks"]], ["cart-addition--1", "cart-addition--2"])
        self.assertEqual(selected[0]["id"], "cart-addition")
        self.assertIn("cart-addition", scenario_lookup)

    def test_run_suite_fanout_validates_each_duplicate(self) -> None:
        suite = BUILTIN_SUITES["common-web"]
        fanout_payload = {
            "job": {
                "started_at": "2026-03-24T00:00:00+00:00",
                "finished_at": "2026-03-24T00:00:05+00:00",
            },
            "summary": {
                "total": 2,
                "completed": 2,
                "failed": 0,
                "cancelled": 0,
                "run_creation_failed": 0,
                "wait_timeout": 0,
                "polling_error": 0,
            },
            "results": [
                {
                    "id": "form-fill-submit--1",
                    "meta": {"scenario_id": "form-fill-submit", "replica": 1},
                    "run_id": "run_1",
                    "outcome": "COMPLETED",
                    "run_status": "COMPLETED",
                    "duration_seconds": 1.0,
                    "error": None,
                    "run_response": {
                        "status": "COMPLETED",
                        "result": {
                            "submitted": True,
                            "text_input_value": "TinyFish CLI Test",
                            "dropdown_value": "Two",
                            "confirmation_heading": "Form submitted",
                            "confirmation_message": "Received!",
                        },
                    },
                },
                {
                    "id": "form-fill-submit--2",
                    "meta": {"scenario_id": "form-fill-submit", "replica": 2},
                    "run_id": "run_2",
                    "outcome": "COMPLETED",
                    "run_status": "COMPLETED",
                    "duration_seconds": 1.0,
                    "error": None,
                    "run_response": {
                        "status": "COMPLETED",
                        "result": {
                            "submitted": True,
                            "text_input_value": "TinyFish CLI Test",
                            "dropdown_value": "Two",
                            "confirmation_heading": "Form submitted",
                            "confirmation_message": "Received!",
                        },
                    },
                },
            ],
        }
        with patch("tinyfish_cli.suite_runner.run_fanout", return_value=(fanout_payload, 0)):
            summary, exit_code = run_suite_fanout(
                client=None,
                suite=suite,
                scenario_ids=["form-fill-submit"],
                duplicates=2,
                max_concurrency=5,
                interval=0.0,
                wait_timeout=10.0,
                fail_fast=False,
                include_responses=False,
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["summary"]["passed"], 2)
        self.assertEqual(summary["results"][0]["scenario_id"], "form-fill-submit")
