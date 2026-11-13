from __future__ import annotations

import pytest

from envxx import http, store


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own ENVXX_HOME."""
    home = tmp_path / "home"
    monkeypatch.setenv(store.HOME_ENV, str(home))
    return home


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Fail fast if a test reaches the network without @pytest.mark.network.

    Only the client factory is patched, so tests that install their own
    MockTransport client still work (their patch is applied later).
    """
    if request.node.get_closest_marker("network"):
        return

    def blocked(*args, **kwargs):
        raise AssertionError("network access in a unit test")

    monkeypatch.setattr(http, "client", blocked)
