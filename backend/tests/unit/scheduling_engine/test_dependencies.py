"""Unit tests for app.scheduling_engine.dependencies.cycle_check. See design doc §6.1."""

from app.scheduling_engine.dependencies import cycle_check


def test_empty_edge_set_has_no_cycle() -> None:
    assert cycle_check([]) is False


def test_single_edge_has_no_cycle() -> None:
    assert cycle_check([("inspection", "prepare_car")]) is False


def test_chain_with_no_cycle() -> None:
    edges = [("c", "b"), ("b", "a")]
    assert cycle_check(edges) is False


def test_direct_two_node_cycle_is_detected() -> None:
    edges = [("a", "b"), ("b", "a")]
    assert cycle_check(edges) is True


def test_indirect_three_node_cycle_is_detected() -> None:
    edges = [("a", "b"), ("b", "c"), ("c", "a")]
    assert cycle_check(edges) is True


def test_self_loop_is_a_cycle() -> None:
    assert cycle_check([("a", "a")]) is True


def test_diamond_shape_is_not_a_cycle() -> None:
    # a depends on b and c; both b and c depend on d. No cycle.
    edges = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]
    assert cycle_check(edges) is False


def test_cycle_in_one_of_several_disconnected_components_is_detected() -> None:
    edges = [("x", "y"), ("a", "b"), ("b", "c"), ("c", "a")]
    assert cycle_check(edges) is True


def test_existing_edges_plus_a_proposed_edge_that_would_close_a_cycle() -> None:
    # Simulates a save-time check: "b" already depends on "a"; proposing that "a"
    # depend on "b" too would close a cycle and must be rejected.
    existing = [("b", "a")]
    proposed = ("a", "b")
    assert cycle_check([*existing, proposed]) is True
