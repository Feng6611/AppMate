"""Tests for competitor_research."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))


def test_module_imports():
    import competitor_research  # noqa: F401


def test_constants_match_spec():
    import competitor_research as cr
    assert cr.SERP_LIMIT == 200
    assert cr.MIN_OUTRANK_COUNT == 3
    assert cr.MAX_CANDIDATES_BEFORE_LLM == 25
    assert cr.DESCRIPTION_TRUNCATE == 200
    assert cr.TOP_N_RIVALS == 10
    assert cr.MIN_RIVALS_FOR_REPORT == 3
    assert cr.TOP_K_KEYWORDS_PER_CARD == 3
    assert cr.SELF_NORANK_CEILING == 200
