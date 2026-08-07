"""Dependency-graph cycle detection. See design doc §6.1.

Cycle check runs at save time - a TaskInstance cannot be saved with a dependency
list that would create a direct or indirect cycle. This is the *only* cycle
detection in the system: §6.1 (Revision 9) establishes that no topological sort is
needed at scheduling time, because the `blocked` status gate already guarantees
every scheduling candidate's dependencies are `completed`.
"""

from __future__ import annotations

from collections.abc import Iterable

_WHITE, _GRAY, _BLACK = 0, 1, 2


def cycle_check(edges: Iterable[tuple[str, str]]) -> bool:
    """True if the given dependency edges contain a direct or indirect cycle.

    Each edge is `(dependent_id, dependency_id)`: the dependent cannot start until
    the dependency completes (§3.3). Callers pass the full edge set to check -
    typically the instance's existing dependencies plus any proposed new ones -
    so a save can be rejected with `cycle_detected` before it's persisted.
    """
    graph: dict[str, list[str]] = {}
    for dependent, dependency in edges:
        graph.setdefault(dependent, []).append(dependency)
        graph.setdefault(dependency, [])

    color: dict[str, int] = dict.fromkeys(graph, _WHITE)

    def visit(node: str) -> bool:
        color[node] = _GRAY
        for neighbor in graph[node]:
            if color[neighbor] == _GRAY:
                return True
            if color[neighbor] == _WHITE and visit(neighbor):
                return True
        color[node] = _BLACK
        return False

    return any(color[node] == _WHITE and visit(node) for node in graph)
