"""Repo-aware LLM planner: JSON schema, parse/validate, keyword last-resort."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from minicoder.scheduler import Planner

PlanKind = Literal["read", "edit", "verify"]

PLAN_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subtasks": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Stable subtask id used by depends_on",
                    },
                    "description": {
                        "type": "string",
                        "description": "What this worker should do",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["read", "edit", "verify"],
                        "description": "read = optional context; edit = change files; verify = run tests",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Source files this subtask may edit or inspect",
                    },
                    "failing_tests": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Failing test nodes or files owned by this subtask",
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": ["string", "integer"]},
                        "description": "Ids or 0-based indices of prerequisite subtasks",
                    },
                    "priority": {"type": "integer"},
                    "optional": {"type": "boolean"},
                },
                "required": ["description", "kind"],
                "additionalProperties": True,
            },
        }
    },
    "required": ["subtasks"],
    "additionalProperties": True,
}

EMIT_PLAN_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "emit_plan",
        "description": "Submit the structured multi-agent plan for this repository.",
        "parameters": PLAN_JSON_SCHEMA,
    },
}


class PlanSubtask(BaseModel):
    """One node in a validated execution plan."""

    id: str | None = None
    description: str
    kind: PlanKind = "edit"
    files: list[str] = Field(default_factory=list)
    failing_tests: list[str] = Field(default_factory=list)
    depends_on: list[str | int] = Field(default_factory=list)
    priority: int = 0
    optional: bool | None = None

    @field_validator("description")
    @classmethod
    def _non_empty_description(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("description must be non-empty")
        return text

    @field_validator("files", "failing_tests", mode="before")
    @classmethod
    def _coerce_str_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value]
        raise ValueError("expected a list of strings")

    @field_validator("depends_on", mode="before")
    @classmethod
    def _coerce_deps(cls, value: Any) -> list[str | int]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("depends_on must be a list")
        out: list[str | int] = []
        for item in value:
            if isinstance(item, bool):
                raise ValueError("depends_on items must be ids or indices")
            if isinstance(item, int):
                out.append(item)
            else:
                out.append(str(item))
        return out


class Plan(BaseModel):
    """Validated planner output."""

    subtasks: list[PlanSubtask]

    @field_validator("subtasks")
    @classmethod
    def _at_least_one(cls, value: list[PlanSubtask]) -> list[PlanSubtask]:
        if not value:
            raise ValueError("plan must contain at least one subtask")
        return value


class InvalidPlanError(ValueError):
    """Raised when planner JSON cannot be turned into a task graph."""


def extract_json_object(text: str) -> Any:
    """Pull the first JSON object/array out of model text."""
    blob = (text or "").strip()
    if not blob:
        raise InvalidPlanError("empty planner response")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", blob, re.IGNORECASE)
    if fence:
        blob = fence.group(1).strip()
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        start_obj = blob.find("{")
        start_arr = blob.find("[")
        starts = [i for i in (start_obj, start_arr) if i >= 0]
        if not starts:
            raise InvalidPlanError("no JSON object in planner response") from None
        start = min(starts)
        decoder = json.JSONDecoder()
        try:
            obj, _end = decoder.raw_decode(blob[start:])
            return obj
        except json.JSONDecodeError as exc:
            raise InvalidPlanError(f"malformed planner JSON: {exc}") from exc


def _as_plan_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"subtasks": payload}
    if isinstance(payload, dict):
        if "subtasks" in payload:
            return payload
        if "steps" in payload and isinstance(payload["steps"], list):
            return {"subtasks": payload["steps"]}
        if "description" in payload or "kind" in payload:
            return {"subtasks": [payload]}
    raise InvalidPlanError("planner JSON must be an object with a subtasks array")


def parse_plan(payload: Any) -> Plan:
    """Validate planner JSON against the schema (via the Pydantic model)."""
    try:
        return Plan.model_validate(_as_plan_dict(payload))
    except ValidationError as exc:
        raise InvalidPlanError(str(exc)) from exc


def parse_plan_text(text: str) -> Plan:
    return parse_plan(extract_json_object(text))


def parse_plan_from_tool_arguments(arguments: str | dict[str, Any]) -> Plan:
    if isinstance(arguments, dict):
        return parse_plan(arguments)
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise InvalidPlanError(f"emit_plan arguments are not valid JSON: {exc}") from exc
    return parse_plan(payload)


def plan_to_steps(plan: Plan) -> list[dict[str, Any]]:
    """Convert a validated plan into scheduler step dicts.

    ``depends_on`` values may be subtask ids or 0-based indices.
    """
    id_to_index: dict[str, int] = {}
    for i, sub in enumerate(plan.subtasks):
        id_to_index[str(i)] = i
        if sub.id:
            id_to_index[sub.id] = i

    steps: list[dict[str, Any]] = []
    for i, sub in enumerate(plan.subtasks):
        deps: list[int] = []
        for dep in sub.depends_on:
            if isinstance(dep, int):
                if dep < 0 or dep >= len(plan.subtasks) or dep == i:
                    raise InvalidPlanError(f"invalid depends_on index {dep}")
                deps.append(dep)
                continue
            if dep not in id_to_index:
                raise InvalidPlanError(f"unknown depends_on id {dep!r}")
            idx = id_to_index[dep]
            if idx == i:
                raise InvalidPlanError(f"subtask {dep!r} depends on itself")
            deps.append(idx)
        optional = sub.optional
        if optional is None:
            optional = sub.kind == "read"
        steps.append(
            {
                "id": sub.id or str(i),
                "description": sub.description,
                "kind": sub.kind,
                "files": list(sub.files),
                "failing_tests": list(sub.failing_tests),
                "depends_on": deps,
                "priority": sub.priority,
                "optional": bool(optional),
            }
        )
    if _has_cycle(steps):
        raise InvalidPlanError("plan has cyclic dependencies")
    return steps


def _has_cycle(steps: list[dict[str, Any]]) -> bool:
    n = len(steps)
    adj: list[list[int]] = [[] for _ in range(n)]
    for i, step in enumerate(steps):
        for dep in step.get("depends_on") or []:
            if isinstance(dep, int) and 0 <= dep < n:
                adj[dep].append(i)
    color = [0] * n

    def dfs(u: int) -> bool:
        color[u] = 1
        for v in adj[u]:
            if color[v] == 1:
                return True
            if color[v] == 0 and dfs(v):
                return True
        color[u] = 2
        return False

    return any(color[i] == 0 and dfs(i) for i in range(n))


def keyword_fallback_steps(task: str) -> list[dict[str, Any]]:
    """Last-resort keyword templates from ``Planner.decompose_coding_task``."""
    return Planner.decompose_coding_task(task)


def planner_user_prompt(task: str, exploration_summary: str) -> str:
    schema_text = json.dumps(PLAN_JSON_SCHEMA, indent=2)
    return (
        "You are MiniCoder's planner, not an editor. Do not modify files.\n"
        "Given the user task and a short exploration of the repository, emit a "
        "structured plan of subtasks.\n\n"
        "Rules:\n"
        "- Split independent bugs/features that live in separate files or modules "
        "into separate kind=edit subtasks.\n"
        "- Each edit subtask must list the source files it may change and the "
        "failing tests that belong to it.\n"
        "- Do not assign the same file to two edit subtasks that can run at the "
        "same time (no shared files among independent edits).\n"
        "- Add a kind=verify subtask that depends on every edit and runs the full "
        "test suite, unless there is only one edit.\n"
        "- Exploration (file tree, pytest, related files) is already done; only "
        "add kind=read subtasks if extra investigation is required.\n"
        "- If there is only one independent bug/module, emit a single edit "
        "subtask (the coordinator will fall back to a single agent).\n"
        "- Call emit_plan with JSON matching this schema, or reply with that JSON "
        "only.\n\n"
        f"Schema:\n{schema_text}\n\n"
        f"User task:\n{task}\n\n"
        f"Exploration notes:\n{exploration_summary}\n"
    )
