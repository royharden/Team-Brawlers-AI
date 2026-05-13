"""Tests for /v1/lineage — master plan §4 / §8.2."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentforge.api.routes_lineage import set_lineage
from agentforge.memory.schemas import MutatedAttack
from agentforge.redteam.lineage import AttackLineage


def _build_lineage() -> AttackLineage:
    lin = AttackLineage()
    root = MutatedAttack(
        attack_id="root-1",
        parent_attack_id=None,
        seed_id="seed-a",
        category="prompt_injection",
        strategy="single_turn",
        mutator_chain=[],
        rendered_prompt="r",
    )
    child = MutatedAttack(
        attack_id="child-1",
        parent_attack_id="root-1",
        seed_id="seed-a",
        category="prompt_injection",
        strategy="single_turn",
        mutator_chain=["paraphrase"],
        rendered_prompt="r2",
    )
    lin.record(root)
    lin.record(child)
    return lin


@pytest.mark.unit
def test_lineage_tree(client: TestClient) -> None:
    set_lineage(_build_lineage())
    try:
        r = client.get("/v1/lineage/root-1")
        assert r.status_code == 200
        body = r.json()
        assert body["attack_id"] == "root-1"
        assert len(body["children"]) == 1
        assert body["children"][0]["attack_id"] == "child-1"
    finally:
        set_lineage(AttackLineage())


@pytest.mark.unit
def test_lineage_404_for_unknown(client: TestClient) -> None:
    set_lineage(AttackLineage())  # empty
    r = client.get("/v1/lineage/no-such-attack")
    assert r.status_code == 404
