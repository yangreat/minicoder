"""Unit tests for plan JSON schema validation and keyword last-resort."""

from __future__ import annotations

import pytest

from minicoder.planner import (
    InvalidPlanError,
    extract_json_object,
    keyword_fallback_steps,
    parse_plan,
    parse_plan_text,
    plan_to_steps,
)
from minicoder.scheduler import Planner, TaskScheduler


def test_parse_plan_accepts_fenced_json() -> None:
    text = """
Here is the plan:
```json
{
  "subtasks": [
    {"id": "a", "description": "Fix pricing", "kind": "edit", "files": ["pricing.py"],
     "failing_tests": ["test_pricing.py"]},
    {"id": "b", "description": "Fix shipping", "kind": "edit", "files": ["shipping.py"],
     "failing_tests": ["test_shipping.py"]}
  ]
}
```
"""
    plan = parse_plan_text(text)
    steps = plan_to_steps(plan)
    assert len(steps) == 2
    assert steps[0]["files"] == ["pricing.py"]
    assert steps[1]["failing_tests"] == ["test_shipping.py"]
    scheduler = TaskScheduler()
    Planner.create_task_graph(steps, scheduler)
    tasks = list(scheduler.tasks.values())
    assert len(Planner.independent_edit_tasks(tasks)) == 2
    assert not Planner.should_fallback_to_single(tasks)


def test_parse_plan_list_payload() -> None:
    plan = parse_plan(
        [
            {"description": "only one", "kind": "edit", "files": ["a.py"]},
        ]
    )
    steps = plan_to_steps(plan)
    scheduler = TaskScheduler()
    Planner.create_task_graph(steps, scheduler)
    assert Planner.should_fallback_to_single(list(scheduler.tasks.values()))


def test_invalid_plan_json_raises() -> None:
    with pytest.raises(InvalidPlanError):
        parse_plan_text("{not json")
    with pytest.raises(InvalidPlanError):
        parse_plan({"subtasks": "nope"})
    with pytest.raises(InvalidPlanError):
        parse_plan({"subtasks": [{"description": "", "kind": "edit"}]})


def test_cyclic_depends_on_rejected() -> None:
    with pytest.raises(InvalidPlanError, match="cyclic"):
        plan_to_steps(
            parse_plan(
                {
                    "subtasks": [
                        {
                            "id": "a",
                            "description": "A",
                            "kind": "edit",
                            "depends_on": ["b"],
                        },
                        {
                            "id": "b",
                            "description": "B",
                            "kind": "edit",
                            "depends_on": ["a"],
                        },
                    ]
                }
            )
        )


def test_extract_json_object_from_prose() -> None:
    obj = extract_json_object('noise {"subtasks": [{"description": "x", "kind": "edit"}]} trailing')
    assert obj["subtasks"][0]["kind"] == "edit"


def test_keyword_fallback_still_available() -> None:
    steps = keyword_fallback_steps("Fix the bug")
    assert any(s.get("kind") == "edit" for s in steps)
    impl = keyword_fallback_steps("Implement the feature")
    scheduler = TaskScheduler()
    Planner.create_task_graph(impl, scheduler)
    assert len(Planner.independent_edit_tasks(list(scheduler.tasks.values()))) == 2
