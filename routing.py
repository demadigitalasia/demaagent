"""Durable, capability-based Mission Control workflow routing.

The workflow definitions live in ``workflows.json``; this module only provides
bounded validation, atomic persistence, and deterministic preview. It never
launches agents or performs external writes.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
ROUTING_CONFIG_PATH = BASE_DIR / "workflows.json"
BACKUP_SUFFIX = ".bak"
SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
SAFE_CAPABILITY_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
PATH_TRAVERSAL_RE = re.compile(r"(?:^|[/\\])\.\.(?:[/\\]|$)")
ABSOLUTE_PATH_RE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\])")
SECRET_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|credential|"
    r"authorization|private[_-]?key|bearer\s+eyJ)",
    re.IGNORECASE,
)

MAX_CONFIG_BYTES = 512 * 1024
MAX_WORKFLOWS = 50
MAX_STAGES = 24
MAX_RULES = 100
MAX_LIST = 32
MAX_STRING = 2000
APPROVAL_VALUES = {"none", "lead_review", "approval_required", "external_write"}
AVAILABILITY_VALUES = {"on_demand", "unavailable", "disabled"}
METADATA_FILTER_KEYS = frozenset({
    "runtime_mode", "runtime_adapter", "approval_policy", "availability", "parent_id",
})


class RoutingValidationError(ValueError):
    """Raised when owner-supplied routing data is unsafe or inconsistent."""


def _fail(message: str) -> None:
    raise RoutingValidationError(message)


def _iter_strings(value: Any, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_strings(key, f"{path}.<key>")
            yield from _iter_strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_strings(item, f"{path}[{index}]")


def _check_safe_strings(value: Any) -> None:
    for path, text in _iter_strings(value):
        if len(text) > MAX_STRING:
            _fail(f"string terlalu panjang: {path}")
        if "\x00" in text:
            _fail(f"NUL tidak diizinkan: {path}")
        if SECRET_RE.search(text):
            _fail(f"nilai sensitif tidak diizinkan: {path}")
        if ABSOLUTE_PATH_RE.search(text) or PATH_TRAVERSAL_RE.search(text):
            _fail(f"absolute path/path traversal tidak diizinkan: {path}")


def _bounded_string(value: Any, field: str, *, required: bool = True, limit: int = MAX_STRING) -> str:
    if not isinstance(value, str):
        if not required and value is None:
            return ""
        _fail(f"{field} harus string")
    text = value.strip()
    if required and not text:
        _fail(f"{field} wajib diisi")
    if len(text) > limit:
        _fail(f"{field} terlalu panjang")
    return text


def _bounded_list(value: Any, field: str, *, limit: int = MAX_LIST) -> list[str]:
    if not isinstance(value, list):
        _fail(f"{field} harus list")
    if len(value) > limit:
        _fail(f"{field} terlalu panjang")
    result = []
    for item in value:
        text = _bounded_string(item, field, limit=120)
        result.append(text)
    if len(set(result)) != len(result):
        _fail(f"{field} harus unik")
    return result


def _validate_id(value: Any, field: str) -> str:
    text = _bounded_string(value, field, limit=64)
    if not SAFE_ID_RE.fullmatch(text):
        _fail(f"{field} memiliki format tidak valid")
    return text


def _validate_capability(value: Any, field: str) -> str:
    text = _bounded_string(value, field, limit=64)
    if not SAFE_CAPABILITY_RE.fullmatch(text):
        _fail(f"{field} memiliki format tidak valid")
    return text


def _validate_metadata_filters(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 8:
        _fail(f"{field} harus object bounded")
    result: dict[str, Any] = {}
    for raw_key, raw_expected in value.items():
        key = _bounded_string(raw_key, f"{field}.key", limit=64)
        if key not in METADATA_FILTER_KEYS:
            _fail(f"{field} field tidak didukung: {key}")
        if isinstance(raw_expected, str):
            result[key] = _bounded_string(raw_expected, f"{field}.{key}", limit=120)
        elif isinstance(raw_expected, list):
            result[key] = _bounded_list(raw_expected, f"{field}.{key}", limit=16)
        else:
            _fail(f"{field}.{key} harus string atau list")
    return result


def routing_metadata(agent: dict) -> dict:
    raw = agent.get("routing")
    if not isinstance(raw, dict):
        raw = agent.get("routing_metadata")
    return raw if isinstance(raw, dict) else {}


def _roster_index(roster: list[dict]) -> tuple[dict[str, dict], set[str]]:
    if not isinstance(roster, list):
        _fail("roster harus list")
    by_id: dict[str, dict] = {}
    capabilities: set[str] = set()
    for index, agent in enumerate(roster):
        if not isinstance(agent, dict):
            _fail(f"roster[{index}] harus object")
        agent_id = _validate_id(agent.get("id"), f"roster[{index}].id")
        if agent_id in by_id:
            _fail(f"ID agent duplikat: {agent_id}")
        by_id[agent_id] = agent
        metadata = routing_metadata(agent)
        raw_caps = metadata.get("capabilities", [])
        if not isinstance(raw_caps, list):
            _fail(f"routing capabilities tidak valid: {agent_id}")
        for cap in raw_caps:
            capabilities.add(_validate_capability(cap, f"agent {agent_id}.capabilities"))
    return by_id, capabilities


def _validate_stage(stage: Any, workflow_id: str, stage_ids: set[str], agent_ids: set[str], declared_caps: set[str]) -> dict:
    if not isinstance(stage, dict):
        _fail(f"workflow {workflow_id}: stage harus object")
    stage_id = _validate_id(stage.get("id"), f"workflow {workflow_id}.stage.id")
    if stage_id in stage_ids:
        _fail(f"workflow {workflow_id}: stage ID duplikat {stage_id}")
    stage_ids.add(stage_id)
    result = copy.deepcopy(stage)
    result["id"] = stage_id
    result["name"] = _bounded_string(stage.get("name", stage_id), f"stage {stage_id}.name", limit=160)
    caps = [_validate_capability(x, f"stage {stage_id}.capabilities") for x in _bounded_list(stage.get("capabilities", []), f"stage {stage_id}.capabilities")]
    unknown_caps = sorted(set(caps) - declared_caps)
    if unknown_caps:
        _fail(f"stage {stage_id} capability tidak dikenal: {', '.join(unknown_caps[:3])}")
    result["capabilities"] = caps
    result["keywords"] = _bounded_list(stage.get("keywords", []), f"stage {stage_id}.keywords", limit=20)
    result["exclude_tags"] = _bounded_list(stage.get("exclude_tags", []), f"stage {stage_id}.exclude_tags", limit=20)
    metadata_filters = _validate_metadata_filters(
        stage.get("metadata_filters", {}), f"stage {stage_id}.metadata_filters"
    )
    legacy_runtime_mode = stage.get("runtime_mode")
    if legacy_runtime_mode is not None:
        legacy_runtime_mode = _bounded_string(
            legacy_runtime_mode, f"stage {stage_id}.runtime_mode", limit=64
        )
        existing_mode = metadata_filters.get("runtime_mode")
        if existing_mode is not None and existing_mode != legacy_runtime_mode:
            _fail(f"stage {stage_id} runtime_mode tidak konsisten dengan metadata_filters")
        metadata_filters["runtime_mode"] = legacy_runtime_mode
        result["runtime_mode"] = legacy_runtime_mode
    result["metadata_filters"] = metadata_filters
    result["candidate_agent_ids"] = _bounded_list(stage.get("candidate_agent_ids", []), f"stage {stage_id}.candidate_agent_ids", limit=50)
    unknown_agents = sorted(set(result["candidate_agent_ids"]) - agent_ids)
    if unknown_agents:
        _fail(f"stage {stage_id} mereferensikan agent tidak dikenal: {', '.join(unknown_agents[:3])}")
    result["depends_on"] = _bounded_list(stage.get("depends_on", []), f"stage {stage_id}.depends_on", limit=MAX_STAGES)
    if stage_id in result["depends_on"] and not bool(stage.get("allow_self_loop", False)):
        _fail(f"stage {stage_id} memiliki self-loop tanpa allow_self_loop")
    result["approval"] = stage.get("approval", "approval_required")
    if result["approval"] not in APPROVAL_VALUES:
        _fail(f"stage {stage_id}.approval tidak valid")
    if "executor_ref" in stage:
        result["executor_ref"] = _bounded_string(stage.get("executor_ref"), f"stage {stage_id}.executor_ref", limit=120)
    result["allow_self_loop"] = bool(stage.get("allow_self_loop", False))
    return result


def validate_config(config: Any, roster: list[dict]) -> dict:
    if not isinstance(config, dict):
        _fail("config harus object")
    _check_safe_strings(config)
    by_id, roster_caps = _roster_index(roster)
    version = config.get("version", 1)
    if version != 1:
        _fail("version config tidak didukung")
    result = copy.deepcopy(config)
    result["version"] = 1
    default_workflow = _validate_id(config.get("default_workflow"), "default_workflow")
    result["default_workflow"] = default_workflow

    rules = config.get("routing_rules", [])
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        _fail("routing_rules harus list bounded")
    rule_ids: set[str] = set()
    declared_caps = set(roster_caps)
    normalized_rules = []
    for rule in rules:
        if not isinstance(rule, dict):
            _fail("routing rule harus object")
        rule_id = _validate_id(rule.get("id"), "routing_rule.id")
        if rule_id in rule_ids:
            _fail(f"routing rule ID duplikat: {rule_id}")
        rule_ids.add(rule_id)
        capability = _validate_capability(rule.get("capability"), f"routing_rule {rule_id}.capability")
        declared_caps.add(capability)
        row = copy.deepcopy(rule)
        row["id"] = rule_id
        row["capability"] = capability
        row["keywords"] = _bounded_list(rule.get("keywords", []), f"routing_rule {rule_id}.keywords", limit=20)
        priority = rule.get("priority", 0)
        if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 1000:
            _fail(f"routing_rule {rule_id}.priority tidak valid")
        row["priority"] = priority
        normalized_rules.append(row)
    result["routing_rules"] = normalized_rules

    workflows = config.get("workflows")
    if not isinstance(workflows, list) or not workflows or len(workflows) > MAX_WORKFLOWS:
        _fail("workflows harus list non-empty bounded")
    workflow_ids: set[str] = set()
    normalized_workflows = []
    for workflow in workflows:
        if not isinstance(workflow, dict):
            _fail("workflow harus object")
        workflow_id = _validate_id(workflow.get("id"), "workflow.id")
        if workflow_id in workflow_ids:
            _fail(f"workflow ID duplikat: {workflow_id}")
        workflow_ids.add(workflow_id)
        row = copy.deepcopy(workflow)
        row["id"] = workflow_id
        row["name"] = _bounded_string(workflow.get("name", workflow_id), f"workflow {workflow_id}.name", limit=160)
        row["keywords"] = _bounded_list(workflow.get("keywords", []), f"workflow {workflow_id}.keywords", limit=30)
        row["capabilities"] = [_validate_capability(x, f"workflow {workflow_id}.capabilities") for x in _bounded_list(workflow.get("capabilities", []), f"workflow {workflow_id}.capabilities", limit=20)]
        declared_caps.update(row["capabilities"])
        priority = workflow.get("priority", 0)
        if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 1000:
            _fail(f"workflow {workflow_id}.priority tidak valid")
        row["priority"] = priority
        gates = _bounded_list(workflow.get("approval_gates", []), f"workflow {workflow_id}.approval_gates", limit=20)
        if any(gate not in APPROVAL_VALUES and gate not in {"external_write", "publish", "deploy", "delete"} for gate in gates):
            _fail(f"workflow {workflow_id}.approval_gates tidak valid")
        row["approval_gates"] = gates
        stages = workflow.get("stages")
        if not isinstance(stages, list) or not stages or len(stages) > MAX_STAGES:
            _fail(f"workflow {workflow_id}.stages harus list non-empty bounded")
        stage_ids: set[str] = set()
        row["stages"] = [_validate_stage(stage, workflow_id, stage_ids, set(by_id), declared_caps) for stage in stages]
        for stage in row["stages"]:
            unknown_dependencies = sorted(set(stage["depends_on"]) - stage_ids)
            if unknown_dependencies:
                _fail(f"stage {stage['id']} dependency tidak dikenal: {', '.join(unknown_dependencies[:3])}")
        normalized_workflows.append(row)
    if default_workflow not in workflow_ids:
        _fail("default_workflow tidak ditemukan")
    result["workflows"] = normalized_workflows
    # Re-validate stage capabilities after all workflow/rule declarations are known.
    for workflow in result["workflows"]:
        for stage in workflow["stages"]:
            unknown = sorted(set(stage["capabilities"]) - declared_caps)
            if unknown:
                _fail(f"stage capability tidak dikenal: {', '.join(unknown[:3])}")
    return result


def validate_agent_routing_metadata(metadata: Any, agent_ids: set[str] | None = None) -> dict:
    if not isinstance(metadata, dict):
        _fail("routing metadata harus object")
    _check_safe_strings(metadata)
    result = copy.deepcopy(metadata)
    for field in ("capabilities", "tags", "accepts", "outputs"):
        result[field] = _bounded_list(metadata.get(field, []), f"routing.{field}", limit=32)
    for capability in result["capabilities"]:
        _validate_capability(capability, "routing.capabilities")
    parent_id = metadata.get("parent_id")
    if parent_id is not None:
        parent_id = _validate_id(parent_id, "routing.parent_id")
        if agent_ids is not None and parent_id not in agent_ids:
            _fail(f"routing.parent_id agent tidak dikenal: {parent_id}")
    result["parent_id"] = parent_id
    result["runtime_owner"] = _validate_id(metadata.get("runtime_owner"), "routing.runtime_owner")
    if agent_ids is not None and result["runtime_owner"] not in agent_ids:
        _fail(f"routing.runtime_owner agent tidak dikenal: {result['runtime_owner']}")
    result["runtime_mode"] = _bounded_string(metadata.get("runtime_mode", "specialist"), "routing.runtime_mode", limit=64)
    result["approval_policy"] = _bounded_string(metadata.get("approval_policy", "approval_required"), "routing.approval_policy", limit=64)
    if result["approval_policy"] not in APPROVAL_VALUES:
        _fail("routing.approval_policy tidak valid")
    priority = metadata.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 1000:
        _fail("routing.priority tidak valid")
    result["priority"] = priority
    result["availability"] = metadata.get("availability", "on_demand")
    if result["availability"] not in AVAILABILITY_VALUES:
        _fail("routing.availability tidak valid")
    result["available"] = bool(metadata.get("available", True))
    return result


def _agent_candidate(agent: dict, stage: dict) -> tuple[bool, list[str]]:
    metadata = routing_metadata(agent)
    reasons: list[str] = []
    availability = metadata.get("availability", "on_demand")
    if metadata.get("available", True) is False or availability in {"disabled", "unavailable"}:
        return False, ["configured unavailable"]
    required = set(stage.get("capabilities", []))
    actual = set(metadata.get("capabilities", [])) if isinstance(metadata.get("capabilities"), list) else set()
    missing = sorted(required - actual)
    if missing:
        return False, [f"missing capability: {', '.join(missing[:3])}"]
    candidate_ids = stage.get("candidate_agent_ids") or []
    if candidate_ids and agent.get("id") not in candidate_ids:
        return False, ["not in configured candidate set"]
    excluded = set(stage.get("exclude_tags", []))
    tags = set(metadata.get("tags", [])) if isinstance(metadata.get("tags"), list) else set()
    if excluded & tags:
        return False, [f"excluded tag: {sorted(excluded & tags)[0]}"]
    metadata_filters = stage.get("metadata_filters") or {}
    if not metadata_filters and stage.get("runtime_mode"):
        metadata_filters = {"runtime_mode": stage["runtime_mode"]}
    for key, expected in metadata_filters.items():
        actual = metadata.get(key)
        if isinstance(expected, list):
            matches = actual in expected
        else:
            matches = actual == expected
        if not matches:
            return False, [f"metadata filter mismatch: {key}"]
    reasons.append("matched capabilities")
    if metadata_filters:
        reasons.append("matched metadata filters")
    reasons.append(f"priority {metadata.get('priority', 0)}")
    reasons.append(f"configured availability {availability}")
    return True, reasons


def preview_route(config: dict, roster: list[dict], task_text: str, capability_hints: list[str] | None = None) -> dict:
    if not isinstance(task_text, str) or not task_text.strip() or len(task_text) > 4000:
        _fail("task_text wajib 1-4000 karakter")
    hints = capability_hints or []
    if not isinstance(hints, list) or len(hints) > 20:
        _fail("capability_hints harus list bounded")
    hints = [_validate_capability(item, "capability_hints") for item in hints]
    normalized = validate_config(config, roster)
    text = task_text.casefold()
    workflow_scores = []
    rules = normalized.get("routing_rules", [])
    for workflow in normalized["workflows"]:
        matched_caps = set(hints) & set(workflow.get("capabilities", []))
        matched_keywords = {keyword for keyword in workflow.get("keywords", []) if keyword.casefold() in text}
        matched_rule_ids = []
        rule_score = 0
        for rule in rules:
            rule_keyword_match = any(keyword.casefold() in text for keyword in rule.get("keywords", []))
            rule_hint_match = rule.get("capability") in hints
            if (rule_keyword_match or rule_hint_match) and rule.get("capability") in workflow.get("capabilities", []):
                matched_rule_ids.append(rule["id"])
                matched_caps.add(rule["capability"])
                rule_score += int(rule.get("priority", 0))
        score = int(workflow.get("priority", 0)) + rule_score + len(matched_caps) * 100 + len(matched_keywords) * 10
        workflow_scores.append((score, workflow, sorted(matched_caps), sorted(matched_keywords), sorted(matched_rule_ids)))
    matching = [item for item in workflow_scores if item[2] or item[3] or item[4]]
    if matching:
        score, workflow, matched_caps, matched_keywords, matched_rule_ids = sorted(
            matching,
            key=lambda item: (-item[0], -item[1].get("priority", 0), item[1]["id"]),
        )[0]
    else:
        score, workflow, matched_caps, matched_keywords, matched_rule_ids = next(
            item for item in workflow_scores if item[1]["id"] == normalized["default_workflow"]
        )
    configured_agents = {agent.get("id"): agent for agent in roster if isinstance(agent, dict) and isinstance(agent.get("id"), str)}
    stages = []
    approval_gates = list(workflow.get("approval_gates", []))
    for stage in workflow["stages"]:
        candidates = []
        for agent_id in sorted(configured_agents):
            agent = configured_agents[agent_id]
            ok, reasons = _agent_candidate(agent, stage)
            if ok:
                metadata = routing_metadata(agent)
                candidates.append({
                    "id": agent_id,
                    "name": agent.get("name") or agent_id,
                    "priority": metadata.get("priority", 0),
                    "reasons": reasons,
                    "configured_availability": metadata.get("availability", "on_demand"),
                    "runtime_mode": metadata.get("runtime_mode", "unknown"),
                })
        candidates.sort(key=lambda row: (-int(row["priority"]), row["id"]))
        stage_approval = stage.get("approval", "approval_required")
        if stage_approval != "none":
            approval_gates.append(stage_approval)
        selected = candidates[0]["id"] if candidates else None
        stages.append({
            "id": stage["id"],
            "name": stage["name"],
            "selected_agent_id": selected,
            "candidate_agents": candidates,
            "approval": stage_approval,
            "executor_ref": stage.get("executor_ref"),
            "reason": "selected highest configured priority" if selected else "no configured candidate; no runtime launch performed",
        })
    deduped_gates = list(dict.fromkeys(approval_gates))
    return {
        "status": "ok",
        "task_text": task_text,
        "capability_hints": hints,
        "workflow": {
            "id": workflow["id"],
            "name": workflow["name"],
            "score": score,
            "reasons": [
                f"matched capabilities: {', '.join(matched_caps) or 'none'}",
                f"matched keywords: {', '.join(matched_keywords) or 'none'}",
                f"matched rules: {', '.join(matched_rule_ids) or 'none'}",
            ],
        },
        "stages": stages,
        "approval_gates": deduped_gates,
        "execution": {"launched": False, "external_writes": False, "status_source": "configuration_only"},
    }


def atomic_write_config(path: Path, config: dict) -> None:
    path = Path(path)
    encoded = json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > MAX_CONFIG_BYTES:
        _fail("config terlalu besar")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + BACKUP_SUFFIX)
        fd, tmp_backup = tempfile.mkstemp(prefix=f".{backup.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(path.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_backup, backup)
        except Exception:
            try:
                os.unlink(tmp_backup)
            except FileNotFoundError:
                pass
            raise
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        try:
            dir_fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def load_config(path: Path = ROUTING_CONFIG_PATH, roster: list[dict] | None = None) -> dict:
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_CONFIG_BYTES:
        _fail("config terlalu besar")
    data = json.loads(path.read_text(encoding="utf-8"))
    return validate_config(data, roster or []) if roster is not None else data
