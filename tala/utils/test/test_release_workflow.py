import ast
from pathlib import Path
import re

import pytest


class TestReleaseWorkflowFreshness:
    @pytest.mark.parametrize("step_name", ["Install dependency freshness checker", "Check dependency freshness"])
    @pytest.mark.parametrize(
        "event_name,expected", [("pull_request", True), ("push", False), ("release", False),
                                ("workflow_dispatch", False)]
    )
    def test_freshness_is_required_only_for_submission(self, step_name, event_name, expected):
        self.given_tests_workflow()
        self.when_step_condition_is_read(step_name)
        self.when_condition_is_evaluated(event_name)
        self.then_step_matches_submission_policy(expected)

    @pytest.mark.parametrize(
        "step_name", [
            "Install development and package dependencies",
            "Build wheel and source distribution",
            "Check wheel contents and source-test availability",
            "Install wheel and smoke-test packaged assets",
            "Run package test suite",
            "Run lint checks",
        ]
    )
    def test_application_and_artifact_checks_remain_unconditional(self, step_name):
        self.given_tests_workflow()
        self.when_step_condition_is_read(step_name)
        self.then_step_has_no_event_filter()

    def given_tests_workflow(self):
        project_root = Path(__file__).resolve().parents[3]
        self.workflow = (project_root / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    def when_step_condition_is_read(self, step_name):
        start = re.search(r"(?m)^      - name: " + re.escape(step_name) + r"$", self.workflow)
        assert start is not None, f"Missing required workflow step: {step_name}"
        remaining = self.workflow[start.end():]
        end = re.search(r"(?m)^      - ", remaining)
        step = remaining[:end.start()] if end is not None else remaining
        condition = re.search(r"(?m)^        if: (.+)$", step)
        self.condition = condition.group(1) if condition is not None else None

    def when_condition_is_evaluated(self, event_name):
        if self.condition is None:
            self.enabled = True
            return
        field, value = self.condition.split("==")
        assert field.strip() == "github.event_name"
        expected_event = ast.literal_eval(value.strip())
        assert expected_event == "pull_request"
        self.enabled = event_name == expected_event

    def then_step_matches_submission_policy(self, expected):
        assert self.enabled is expected

    def then_step_has_no_event_filter(self):
        assert self.condition is None
