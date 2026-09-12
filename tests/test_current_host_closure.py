from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import fields
from pathlib import Path

from host.otis_tools.adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    AdaptiveHybridProgramme,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "host/otis_tools"
ENTRYPOINTS = frozenset({"__main__", "live_run", "bench_entry", "offline", "run_spec", "evidence_transfer"})
STANDALONE_CURRENT_TOOLS = frozenset()
RETIRED_FRAGMENTS = (
    "active_hybrid",
    "bounded_tight",
    "conditional_",
    "no_write_",
    "programme_status",
    "range_spanning",
    "targeted_equilibrium",
)


def _modules() -> dict[str, Path]:
    return {
        path.stem: path
        for path in PACKAGE.glob("*.py")
        if path.name != "__init__.py"
    }


def _imports(path: Path, available: frozenset[str]) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                if node.module:
                    result.add(node.module.split(".", 1)[0])
                else:
                    result.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif node.module and node.module.startswith("host.otis_tools."):
                result.add(node.module.split(".")[2])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("host.otis_tools."):
                    result.add(alias.name.split(".")[2])
    return frozenset(result)


def _graph() -> dict[str, frozenset[str]]:
    modules = _modules()
    available = frozenset(modules)
    return {name: _imports(path, available) for name, path in modules.items()}


def _closure(
    graph: dict[str, frozenset[str]],
    entrypoints: frozenset[str] = ENTRYPOINTS,
) -> frozenset[str]:
    missing = entrypoints - graph.keys()
    assert not missing, f"current host entrypoints are missing: {sorted(missing)}"
    unresolved = sorted(
        f"{module}->{dependency}"
        for module, dependencies in graph.items()
        for dependency in dependencies
        if dependency not in graph
    )
    assert not unresolved, "unresolved internal imports: " + ", ".join(unresolved)
    reached: set[str] = set()
    pending = list(entrypoints)
    while pending:
        module = pending.pop()
        if module in reached:
            continue
        reached.add(module)
        pending.extend(graph[module] - reached)
    return frozenset(reached)


def test_current_host_dependency_closure_is_acyclic() -> None:
    graph = _graph()
    closure = _closure(graph, ENTRYPOINTS | STANDALONE_CURRENT_TOOLS)
    indegree = {module: 0 for module in closure}
    consumers: dict[str, set[str]] = defaultdict(set)
    for importer in closure:
        for dependency in graph[importer] & closure:
            indegree[importer] += 1
            consumers[dependency].add(importer)
    ready = sorted(module for module, count in indegree.items() if count == 0)
    ordered: list[str] = []
    while ready:
        module = ready.pop()
        ordered.append(module)
        for consumer in consumers[module]:
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                ready.append(consumer)
    cyclic = sorted(module for module, count in indegree.items() if count)
    assert len(ordered) == len(closure), f"current host import cycle: {cyclic}"


def test_current_host_closure_has_no_retired_programme_modules() -> None:
    closure = _closure(_graph())
    retired = sorted(
        module
        for module in closure
        if any(fragment in module for fragment in RETIRED_FRAGMENTS)
    )
    assert not retired, f"retired modules reachable from current host: {retired}"


def test_every_semantic_adaptive_hybrid_module_is_in_current_closure() -> None:
    modules = _modules()
    closure = _closure(_graph()) | STANDALONE_CURRENT_TOOLS
    adaptive_modules = {
        module for module in modules if module.startswith("adaptive_hybrid_")
    }
    assert adaptive_modules <= closure


def test_singleton_programme_api_exactly_matches_current_host_consumers() -> None:
    used: set[str] = set()
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            direct = isinstance(node.value, ast.Name) and node.value.id == "programme"
            member = (
                isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and node.value.attr == "programme"
            )
            if direct or member:
                used.add(node.attr)

    declared = {field.name for field in fields(AdaptiveHybridProgramme)} | {
        name
        for name, value in vars(AdaptiveHybridProgramme).items()
        if isinstance(value, property)
    }
    assert used <= declared, f"undeclared programme fields: {sorted(used - declared)}"
    assert all(hasattr(ADAPTIVE_HYBRID_PROGRAMME, name) for name in used)
    assert ADAPTIVE_HYBRID_PROGRAMME.armable_hybrid_states == frozenset(
        {
            "FREQUENCY_ACQUIRE",
            "PHASE_QUALIFY",
            "HYBRID_TRACKING",
            "PHASE_DEGRADED_FREQUENCY_ONLY",
        }
    )


def test_transaction_acknowledgement_has_no_single_profile_selector() -> None:
    source = (PACKAGE / "adaptive_hybrid_transactions.py").read_text(
        encoding="utf-8"
    )
    assert "HYBRID_TRANSACTION_PROFILE_IDS" not in source
    assert "hybrid_profile" not in source


def test_live_supervisor_cannot_accept_a_structural_preflight_manifest() -> None:
    source = (PACKAGE / "adaptive_hybrid_supervisor.py").read_text(
        encoding="utf-8"
    )
    assert "rehearsal_manifest" not in source
    assert "--rehearsal-manifest" not in source
    assert "validate_rehearsal_run_manifest" not in source
