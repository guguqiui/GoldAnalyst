import threading
import unittest

from gold_analyst.orchestration import create_task_plan, run_task_plan
from gold_analyst.server import new_run


class TaskRunnerTests(unittest.TestCase):
    def test_independent_specialists_run_before_verifier(self):
        barrier = threading.Barrier(2, timeout=2)
        calls = []

        def fake_runner(parent, task, spec, emit, client, findings, evidence):
            calls.append((task["id"], [item["task_id"] for item in findings]))
            if task["agent"] != "verification":
                barrier.wait()
                return {
                    "id": task["id"],
                    "evidence": [{"id": "E1", "url": f"https://example.com/{task['id']}"}],
                    "finding": {
                        "task_id": task["id"], "agent": task["agent"], "status": "supported",
                        "summary": task["goal"], "facts": [], "evidence_ids": ["E1"], "unresolved": [],
                    },
                    "usage": {"input_tokens": 1, "output_tokens": 1, "tool_calls": 1, "search_requests": 0},
                }
            self.assertEqual([item["task_id"] for item in findings], ["market", "cause"])
            self.assertEqual([item["id"] for item in evidence], ["E1", "E2"])
            return {
                "id": task["id"], "evidence": evidence,
                "verification_result": {
                    "status": "insufficient", "fact_results": [],
                    "conflicts": [], "unresolved": [],
                },
                "usage": {"input_tokens": 1, "output_tokens": 1, "tool_calls": 0, "search_requests": 0},
            }

        run = new_run("multi", "最近黄金上涨了多少，为什么上涨", "source_first")
        result = run_task_plan(run, create_task_plan(run["input"]), lambda *args: None,
                               specialist_runner=fake_runner)

        self.assertEqual([item["task_id"] for item in result["findings"]], ["market", "cause"])
        self.assertEqual([item["id"] for item in result["evidence"]], ["E1", "E2"])
        self.assertEqual(result["verification_result"]["status"], "insufficient")
        self.assertEqual(result["usage"]["input_tokens"], 3)
        self.assertEqual(calls[-1], ("verification", ["market", "cause"]))

    def test_same_url_is_reused_even_when_tracking_parameters_differ(self):
        def fake_runner(parent, task, spec, emit, client, findings, evidence):
            usage = {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "search_requests": 0}
            if task["agent"] == "cause":
                return {
                    "evidence": [{
                        "id": "E1", "url": "https://example.com/gold?utm_source=openai",
                        "text": "short", "source_tier": 2,
                    }],
                    "finding": {
                        "task_id": "cause", "agent": "cause", "status": "supported",
                        "summary": "finding", "facts": [], "evidence_ids": ["E1"], "unresolved": [],
                    },
                    "usage": usage,
                }
            return {
                "evidence": evidence + [{
                    "id": "E2", "url": "https://example.com/gold#section",
                    "text": "a more complete page body", "source_tier": 1,
                }],
                "verification_result": {
                    "status": "insufficient", "fact_results": [], "conflicts": [], "unresolved": [],
                },
                "usage": usage,
            }

        run = new_run("multi", "黄金上涨原因", "source_first")
        result = run_task_plan(run, create_task_plan(run["input"]), lambda *args: None,
                               specialist_runner=fake_runner)

        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual(result["evidence"][0]["id"], "E1")
        self.assertEqual(result["evidence"][0]["source_tier"], 1)
        self.assertEqual(result["evidence"][0]["text"], "a more complete page body")

    def test_same_domain_with_different_paths_remains_separate(self):
        def fake_runner(parent, task, spec, emit, client, findings, evidence):
            usage = {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "search_requests": 0}
            if task["agent"] == "cause":
                return {
                    "evidence": [{"id": "E1", "url": "https://example.com/first"}],
                    "finding": {
                        "task_id": "cause", "agent": "cause", "status": "supported",
                        "summary": "finding", "facts": [], "evidence_ids": ["E1"], "unresolved": [],
                    },
                    "usage": usage,
                }
            return {
                "evidence": evidence + [{"id": "E2", "url": "https://example.com/second"}],
                "verification_result": {
                    "status": "insufficient", "fact_results": [], "conflicts": [], "unresolved": [],
                },
                "usage": usage,
            }

        run = new_run("multi", "黄金上涨原因", "source_first")
        result = run_task_plan(run, create_task_plan(run["input"]), lambda *args: None,
                               specialist_runner=fake_runner)

        self.assertEqual([item["id"] for item in result["evidence"]], ["E1", "E2"])

    def test_parallel_findings_are_rewritten_to_the_reused_evidence_id(self):
        def fake_runner(parent, task, spec, emit, client, findings, evidence):
            usage = {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "search_requests": 0}
            if task["agent"] != "verification":
                local_id = "E1" if task["agent"] == "market" else "E7"
                suffix = "?utm_campaign=test" if task["agent"] == "market" else ""
                return {
                    "evidence": [{"id": local_id, "url": "https://example.com/shared" + suffix}],
                    "finding": {
                        "task_id": task["id"], "agent": task["agent"], "status": "supported",
                        "summary": "finding", "facts": [], "evidence_ids": [local_id], "unresolved": [],
                    },
                    "usage": usage,
                }
            self.assertEqual([item["evidence_ids"] for item in findings], [["E1"], ["E1"]])
            self.assertEqual([item["id"] for item in evidence], ["E1"])
            return {
                "evidence": evidence,
                "verification_result": {
                    "status": "insufficient", "fact_results": [],
                    "conflicts": [], "unresolved": [],
                },
                "usage": usage,
            }

        run = new_run("multi", "黄金上涨了多少，为什么上涨", "source_first")
        result = run_task_plan(run, create_task_plan(run["input"]), lambda *args: None,
                               specialist_runner=fake_runner)

        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual([item["evidence_ids"] for item in result["findings"]], [["E1"], ["E1"]])


if __name__ == "__main__":
    unittest.main()
