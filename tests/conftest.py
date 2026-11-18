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
def never_touch_the_real_store(tmp_path, request):
    """Catch a test that lost its sandbox.

    A project store is discovered from the working directory now, so a test
    that clears ENVXX_HOME and changes into a directory tree could write into
    the developer's own ~/.envxx. Tests that exercise discovery on purpose set
    this marker; everything else must stay inside tmp_path.
    """
    yield
    if request.node.get_closest_marker("real_store"):
        return
    home = store.home()
    assert str(home).startswith(str(tmp_path)), (
        f"test resolved the store to {home}, outside its tmp_path"
    )


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


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_store: test exercises store discovery outside its own tmp_path",
    )
