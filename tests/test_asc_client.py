"""Tests for asc_client — focused on the write-method opt-in guard.

The guard is defense-in-depth: even with an over-privileged API key, AppMate's
own code is physically prevented from issuing POST/PUT/PATCH/DELETE requests
unless ``APPMATE_ALLOW_WRITES=1`` is set in the environment.
"""
from __future__ import annotations

import importlib

import pytest

import asc_client


def _reload(monkeypatch, *, allow_writes: bool):
    """Reload asc_client with APPMATE_ALLOW_WRITES set or unset."""
    if allow_writes:
        monkeypatch.setenv("APPMATE_ALLOW_WRITES", "1")
    else:
        monkeypatch.delenv("APPMATE_ALLOW_WRITES", raising=False)
    return importlib.reload(asc_client)


def test_write_opt_in_env_constant_is_stable():
    """The opt-in env var name is part of the public contract — surfaced in
    error messages, docs, and the README."""
    assert asc_client.WRITE_OPT_IN_ENV == "APPMATE_ALLOW_WRITES"


def test_post_blocked_by_default(monkeypatch):
    client = _reload(monkeypatch, allow_writes=False)
    with pytest.raises(PermissionError) as exc:
        client.post("/v1/anything", {"data": {}})
    msg = str(exc.value)
    assert "asc_client.post()" in msg
    assert "APPMATE_ALLOW_WRITES=1" in msg


def test_post_allowed_when_opt_in(monkeypatch):
    """With the opt-in flag set, the guard passes through and post() proceeds
    to its real network call. We stub ``requests.post`` so the test stays
    offline and just verifies the guard does not raise."""
    client = _reload(monkeypatch, allow_writes=True)

    class _StubResponse:
        status_code = 201

        def json(self):
            return {"data": {}}

    captured: dict[str, object] = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _StubResponse()

    monkeypatch.setattr(client.requests, "post", fake_post)
    # Avoid touching the JWT path — make_token reads credentials we don't have.
    monkeypatch.setattr(client, "_auth_headers", lambda: {"Authorization": "Bearer test"})

    r = client.post("/v1/anything", {"data": {"type": "x"}})
    assert r.status_code == 201
    assert captured["url"].endswith("/v1/anything")
    assert captured["json"] == {"data": {"type": "x"}}


def test_get_never_requires_opt_in(monkeypatch):
    """The guard must not interfere with the read path — every workflow uses
    get(), and breaking it would be a regression worse than the original bug."""
    client = _reload(monkeypatch, allow_writes=False)

    class _StubResponse:
        status_code = 200

    monkeypatch.setattr(client, "_auth_headers", lambda: {"Authorization": "Bearer test"})
    monkeypatch.setattr(
        client.requests,
        "get",
        lambda url, headers=None, params=None, timeout=None: _StubResponse(),
    )
    r = client.get("/v1/apps")
    assert r.status_code == 200
