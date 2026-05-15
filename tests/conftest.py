"""Shared test setup.

* Adds ``scripts/`` to ``sys.path`` so test modules can import the workflow
  scripts directly (matches the way every script imports its siblings).
* Stubs ``appmate_config.require_credentials_or_exit`` to a no-op for every
  test by default. The credential gate is exercised explicitly in
  ``test_appmate_config.py`` — those tests reload the ``appmate_config``
  module via ``importlib.reload``, which restores the real function for the
  duration of each test that needs it.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


@pytest.fixture(autouse=True)
def _bypass_credentials_precheck(monkeypatch):
    """No-op the credentials gate for tests that exercise main() dispatch / IO.

    Patched by FQN so the substitution survives an ``importlib.reload`` of the
    module (monkeypatch resolves the attribute on the live ``sys.modules`` entry
    at patch and teardown time).
    """
    monkeypatch.setattr(
        "appmate_config.require_credentials_or_exit",
        lambda *args, **kwargs: None,
    )
