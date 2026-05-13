"""Unit tests for `Tagger` — master plan §8.4."""

from __future__ import annotations

import pytest

from agentforge.documentation.tagger import Tagger, TagSet


@pytest.mark.unit
def test_tag_returns_all_four_mappings() -> None:
    """A known category produces non-empty mappings on all four axes."""
    t = Tagger()
    ts = t.tag("data_exfiltration")
    assert isinstance(ts, TagSet)
    assert ts.owasp_llm_top_10 == ["LLM02", "LLM06"]
    assert ts.avid == ["S0202:Information Leak"]
    # NIST always includes the default plus category-specific.
    assert "Measure 2.7" in ts.nist_ai_rmf
    assert "Manage 2.4" in ts.nist_ai_rmf
    assert "Govern 1.4" in ts.nist_ai_rmf


@pytest.mark.unit
def test_unknown_category_returns_default_nist_only() -> None:
    """An unknown category gets empty OWASP/AVID + the default NIST set."""
    t = Tagger()
    ts = t.tag("nonexistent_category_xyz")
    assert ts.owasp_llm_top_10 == []
    assert ts.owasp_agentic_top_10 == []
    assert ts.avid == []
    assert ts.nist_ai_rmf == ["Measure 2.7", "Manage 2.4"]


@pytest.mark.unit
def test_lookup_json_parses_at_init() -> None:
    """`Tagger()` loads the JSON immediately and exposes the inner dict."""
    t = Tagger()
    assert "owasp_llm_top_10_2025" in t._lookup
    assert "prompt_injection" in t._lookup["owasp_llm_top_10_2025"]
