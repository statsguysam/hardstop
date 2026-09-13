"""Deterministic selection of complete clips under explicit constraints.

The model may suggest requirements and priorities; it never supplies the clip
durations or bypasses this solver. Source order and declared prerequisites are
immutable. No function in this module performs I/O or mutates its arguments.
"""

from __future__ import annotations

from collections.abc import Mapping
import re


MAX_SEGMENTS = 18
_ID = re.compile(r"[a-z][a-z0-9_]*\Z")
_CONSTRAINT_FIELDS = frozenset({
    "max_duration_ms", "required_ids", "excluded_ids", "priorities",
    "evidence", "ambiguities",
})


def _positive_int(value: object, label: str) -> int:
    # bool is an int subclass and must not become a one-millisecond budget.
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _id_list(value: object, label: str, known: set[str] | None = None) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not _ID.fullmatch(item) for item in value
    ):
        raise ValueError(f"{label} must be a list of segment IDs")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must not contain duplicate IDs")
    if known is not None and set(value) - known:
        raise ValueError(f"{label} contains unknown segment IDs")
    return list(value)


def _validate(segments: object, constraints: object) -> tuple[list[dict], dict]:
    """Validate data at the trust boundary and make private shallow copies."""
    if not isinstance(segments, list) or not 1 <= len(segments) <= MAX_SEGMENTS:
        raise ValueError(f"segments must be a list of 1 to {MAX_SEGMENTS} entries")
    normalized = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping):
            raise ValueError(f"segment {index} must be an object")
        identifier = segment.get("id")
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise ValueError(f"segment {index} has an invalid ID")
        duration = _positive_int(segment.get("duration_ms"), f"segment {identifier} duration_ms")
        value = _positive_int(segment.get("value"), f"segment {identifier} value")
        if value > 10:
            raise ValueError(f"segment {identifier} value must be at most 10")
        requires = _id_list(segment.get("requires"), f"segment {identifier} requires")
        normalized.append({"id": identifier, "duration_ms": duration,
                           "value": value, "requires": requires})

    identifiers = [segment["id"] for segment in normalized]
    known = set(identifiers)
    if len(known) != len(identifiers):
        raise ValueError("source catalog contains duplicate segment IDs")
    by_id = {segment["id"]: segment for segment in normalized}
    positions = {identifier: index for index, identifier in enumerate(identifiers)}
    for segment in normalized:
        if set(segment["requires"]) - known:
            raise ValueError(f"segment {segment['id']} requires unknown segment IDs")

    # Diagnose cycles before order, including self-dependencies.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise ValueError("source prerequisite graph contains a cycle")
        if identifier in visited:
            return
        visiting.add(identifier)
        for prerequisite in by_id[identifier]["requires"]:
            visit(prerequisite)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in identifiers:
        visit(identifier)
    for segment in normalized:
        if any(positions[dependency] >= positions[segment["id"]]
               for dependency in segment["requires"]):
            raise ValueError("source order places a prerequisite after its dependent clip")

    if not isinstance(constraints, Mapping):
        raise ValueError("constraints must be an object")
    if set(constraints) != _CONSTRAINT_FIELDS:
        raise ValueError("constraints must contain exactly the six documented fields")
    clean = {
        "max_duration_ms": _positive_int(constraints["max_duration_ms"], "max_duration_ms"),
        "required_ids": _id_list(constraints["required_ids"], "required_ids", known),
        "excluded_ids": _id_list(constraints["excluded_ids"], "excluded_ids", known),
    }
    priorities = constraints["priorities"]
    if not isinstance(priorities, Mapping) or any(key not in known for key in priorities):
        raise ValueError("priorities must map known segment IDs to positive integers")
    clean["priorities"] = {
        identifier: _positive_int(value, f"priority for {identifier}")
        for identifier, value in priorities.items()
    }
    evidence = constraints["evidence"]
    if not isinstance(evidence, list):
        raise ValueError("evidence must be a list")
    for entry in evidence:
        if not isinstance(entry, Mapping) or set(entry) != {"kind", "segment_id", "quote"}:
            raise ValueError("each evidence entry must contain kind, segment_id and quote")
        if not isinstance(entry["kind"], str) or not entry["kind"].strip():
            raise ValueError("evidence kind must be a nonempty string")
        if entry["segment_id"] is not None and (
            not isinstance(entry["segment_id"], str) or entry["segment_id"] not in known
        ):
            raise ValueError("evidence segment_id must be a known ID or null")
        if not isinstance(entry["quote"], str) or not entry["quote"].strip():
            raise ValueError("evidence quote must be a nonempty string")
    clean["evidence"] = [dict(entry) for entry in evidence]
    ambiguities = constraints["ambiguities"]
    if not isinstance(ambiguities, list) or any(
        not isinstance(item, str) or not item.strip() for item in ambiguities
    ):
        raise ValueError("ambiguities must be a list of nonempty strings")
    clean["ambiguities"] = list(ambiguities)
    return normalized, clean


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _seconds(milliseconds: int) -> str:
    """Display exact milliseconds without floating-point rounding or overflow."""
    whole, fraction = divmod(milliseconds, 1000)
    return str(whole) if not fraction else f"{whole}.{fraction:03d}".rstrip("0")


def verify_selection(segments: list[dict], constraints: dict, selected_ids: list[str]) -> dict:
    """Independently recompute whether a proposed selection satisfies the brief.

    This accepts a selection from any source and does not call ``plan`` or trust
    its reported duration/closure. Invalid source or constraint schemas raise
    ValueError. Invalid selections return ``valid: False`` with failed checks.
    The caller must separately verify rendered media and the cloud slide order.
    """
    source, rules = _validate(segments, constraints)
    if not isinstance(selected_ids, list) or any(not isinstance(item, str) for item in selected_ids):
        raise ValueError("selected_ids must be a list of strings")
    by_id = {segment["id"]: segment for segment in source}
    source_ids = list(by_id)
    selected = set(selected_ids)
    known_selection = selected <= set(source_ids)
    unique_selection = len(selected) == len(selected_ids)

    # Deliberately use graph traversal, independently of the optimizer's masks.
    required = set(rules["required_ids"])
    pending = list(required)
    while pending:
        for prerequisite in by_id[pending.pop()]["requires"]:
            if prerequisite not in required:
                required.add(prerequisite)
                pending.append(prerequisite)
    required_closure = [identifier for identifier in source_ids if identifier in required]
    minimum = sum(by_id[identifier]["duration_ms"] for identifier in required)
    duration = sum(by_id[identifier]["duration_ms"] for identifier in selected_ids if identifier in by_id)
    ordered = selected_ids == [identifier for identifier in source_ids if identifier in selected]
    missing_dependencies = sorted({
        prerequisite
        for identifier in selected if identifier in by_id
        for prerequisite in by_id[identifier]["requires"] if prerequisite not in selected
    })
    checks = [
        _check("nonempty_cut", bool(selected_ids), "The output contains at least one complete clip."),
        _check("known_ids", known_selection, "Every selected ID exists in the source catalog."),
        _check("unique_ids", unique_selection, "Each selected clip appears once."),
        _check("source_order", ordered, "Selected clips retain their original presentation order."),
        _check("required_closure", required <= selected, "All mandatory clips and their prerequisites are selected."),
        _check("excluded_absent", not selected.intersection(rules["excluded_ids"]), "No excluded clip is selected."),
        _check("dependencies", not missing_dependencies, "Every selected clip has its declared prerequisites."),
        _check("duration_budget", known_selection and duration <= rules["max_duration_ms"],
               f"Measured clip sum is {duration} ms; budget is {rules['max_duration_ms']} ms."),
        _check("resolved_brief", not rules["ambiguities"], "The brief has no unresolved ambiguities."),
    ]
    return {"valid": all(check["passed"] for check in checks), "duration_ms": duration,
            "minimum_required_ms": minimum, "required_closure": required_closure, "checks": checks}


def plan(segments: list[dict], constraints: dict) -> dict:
    """Find the maximum-value feasible subset, preserving complete source clips.

    Priorities replace source values for ranking only. Ties favor less duration,
    then earlier source clips. Exhaustive enumeration is bounded to 18 clips.
    Invalid input raises ValueError; ambiguity or an impossible brief produces a
    blocked plan with no selected clips. An empty cut is never a valid output.
    """
    source, rules = _validate(segments, constraints)
    count = len(source)
    positions = {segment["id"]: index for index, segment in enumerate(source)}
    source_ids = list(positions)
    closure_masks = []
    for index, segment in enumerate(source):
        closure = 1 << index
        for dependency in segment["requires"]:
            closure |= closure_masks[positions[dependency]]
        closure_masks.append(closure)
    mandatory = 0
    for identifier in rules["required_ids"]:
        mandatory |= closure_masks[positions[identifier]]
    excluded = sum(1 << positions[identifier] for identifier in rules["excluded_ids"])
    required_closure = [identifier for index, identifier in enumerate(source_ids) if mandatory & (1 << index)]
    minimum = sum(segment["duration_ms"] for index, segment in enumerate(source) if mandatory & (1 << index))
    result = {
        "status": "infeasible", "selected_ids": [], "duration_ms": 0,
        "minimum_required_ms": minimum, "required_closure": required_closure,
        "removed_ids": list(source_ids), "reasons": [], "checks": [],
    }

    if rules["ambiguities"]:
        result["status"] = "needs_review"
        result["reasons"] = ["Resolve the brief before creating an output: " + issue for issue in rules["ambiguities"]]
        result["checks"] = [_check("resolved_brief", False, "The brief contains unresolved ambiguities.")]
        return result
    conflicts = [identifier for identifier in required_closure if identifier in rules["excluded_ids"]]
    if conflicts:
        result["reasons"] = [
            "Mandatory clips or their declared prerequisites are also excluded: " + ", ".join(conflicts) + ".",
            f"The mandatory closure is {', '.join(required_closure)} ({_seconds(minimum)} seconds).",
        ]
        result["checks"] = [_check("required_exclusion_conflict", False, result["reasons"][0])]
        return result
    if minimum > rules["max_duration_ms"]:
        result["reasons"] = [
            f"Mandatory clips and prerequisites need {_seconds(minimum)} seconds, exceeding the "
            f"{_seconds(rules['max_duration_ms'])}-second limit by {_seconds(minimum - rules['max_duration_ms'])} seconds.",
            "Required closure: " + ", ".join(required_closure) + ".",
        ]
        result["checks"] = [_check("mandatory_duration", False, result["reasons"][0])]
        return result

    # Each state is accumulated from a smaller subset. Dependencies are checked
    # against the complete subset, not assumed because the subset has a high score.
    state_count = 1 << count
    durations = [0] * state_count
    scores = [0] * state_count
    prerequisite_unions = [0] * state_count
    best_mask = 0
    best_key = None
    for mask in range(1, state_count):
        bit = mask & -mask
        index = bit.bit_length() - 1
        previous = mask ^ bit
        segment = source[index]
        durations[mask] = durations[previous] + segment["duration_ms"]
        scores[mask] = scores[previous] + rules["priorities"].get(segment["id"], segment["value"])
        prerequisite_unions[mask] = prerequisite_unions[previous] | closure_masks[index]
        if mask & excluded or mask & mandatory != mandatory:
            continue
        if durations[mask] > rules["max_duration_ms"] or prerequisite_unions[mask] != mask:
            continue
        indices = tuple(index for index in range(count) if mask & (1 << index))
        key = (-scores[mask], durations[mask], indices)
        if best_key is None or key < best_key:
            best_mask, best_key = mask, key
    if best_key is None:
        result["reasons"] = ["No nonempty selection of complete clips satisfies the exclusions, dependencies and duration budget."]
        result["checks"] = [_check("nonempty_cut", False, result["reasons"][0])]
        return result

    selected_ids = [identifier for index, identifier in enumerate(source_ids) if best_mask & (1 << index)]
    verified = verify_selection(segments, constraints, selected_ids)
    if not verified["valid"]:
        raise RuntimeError("Internal planner verification failed")
    result.update({
        "status": "feasible", "selected_ids": selected_ids,
        "duration_ms": verified["duration_ms"],
        "removed_ids": [identifier for identifier in source_ids if identifier not in selected_ids],
        "checks": verified["checks"],
        "reasons": [
            f"Selected {len(selected_ids)} complete clips totaling {_seconds(verified['duration_ms'])} seconds "
            f"within the {_seconds(rules['max_duration_ms'])}-second limit.",
            "All explicit required clips and declared prerequisites are preserved in source order.",
            "Optional clips maximize the configured priority score; duration and source order break ties.",
        ],
    })
    return result
