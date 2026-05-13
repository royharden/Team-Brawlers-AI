"""AttackLineage tracker tests — master plan §8.2."""

from __future__ import annotations

import pytest

from agentforge.memory.schemas import MutatedAttack
from agentforge.redteam.lineage import AttackLineage


def _attack(aid: str, parent: str | None = None, seed_id: str = "seed_x") -> MutatedAttack:
    return MutatedAttack(
        attack_id=aid,
        parent_attack_id=parent,
        seed_id=seed_id,
        category="prompt_injection",
        strategy="single_turn",
        rendered_prompt="x",
        mutator_chain=["role_wrap.doctor"],
    )


@pytest.mark.unit
def test_record_then_query_parents_and_children() -> None:
    """`AttackLineage.record` then `ancestors` / `descendants` returns expected single-level relationships."""
    lin = AttackLineage()
    lin.record(_attack("root"))
    lin.record(_attack("c1", parent="root"))
    lin.record(_attack("c2", parent="root"))
    assert lin.ancestors("c1") == ["root"]
    assert sorted(lin.descendants("root")) == ["c1", "c2"]


@pytest.mark.unit
def test_ancestors_walk_back_to_root_inclusive_left() -> None:
    """`AttackLineage.ancestors` walks root → leaf exclusive of the leaf."""
    lin = AttackLineage()
    lin.record(_attack("root"))
    lin.record(_attack("a", parent="root"))
    lin.record(_attack("b", parent="a"))
    lin.record(_attack("c", parent="b"))
    # Root → c (exclusive of c)
    assert lin.ancestors("c") == ["root", "a", "b"]


@pytest.mark.unit
def test_descendants_breadth_first_excludes_self() -> None:
    """`AttackLineage.descendants` returns BFS order, excludes the root id."""
    lin = AttackLineage()
    lin.record(_attack("root"))
    lin.record(_attack("a", parent="root"))
    lin.record(_attack("b", parent="a"))
    descendants = lin.descendants("root")
    assert "root" not in descendants
    assert descendants == ["a", "b"]


@pytest.mark.unit
def test_tree_renders_nested_dict_for_ui() -> None:
    """`AttackLineage.tree` renders a nested dict carrying `attack_id`, `seed_id`, `mutator_chain`."""
    lin = AttackLineage()
    lin.record(_attack("root"))
    lin.record(_attack("a", parent="root"))
    tree = lin.tree("root")
    assert tree["attack_id"] == "root"
    assert tree["children"][0]["attack_id"] == "a"
    assert tree["children"][0]["mutator_chain"] == ["role_wrap.doctor"]
