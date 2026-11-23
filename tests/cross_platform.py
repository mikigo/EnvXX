"""Run the suite as if the host were a different platform.

This project branches on the host in several places a Windows-only or
Linux-only run never reaches: the shim format, the shell rc files, the Windows
registry, and the desktop opener. Twice, a test that assumed one platform
passed locally and failed on the Ubuntu runner.

Running the suite natively only covers the host it runs on. This plugin makes
both coverable from one machine:

    PYTHONPATH=tests pytest -p cross_platform --cross-platform=linux

PYTHONPATH is required: -p is resolved before pytest puts tests/ on sys.path.

The patches land on the indirection points, so a test that states its own
platform still wins: those fixtures monkeypatch the same attribute and apply
after this plugin's session-wide patch.
"""
from __future__ import annotations

import pytest

HOSTS = ("windows", "linux", "macos")


def pytest_addoption(parser):
    parser.addoption(
        "--cross-platform",
        action="store",
        default=None,
        choices=HOSTS,
        help="pretend the host is this platform",
    )


@pytest.fixture(scope="session", autouse=True)
def _cross_platform_host(request):
    """Point every host hook at the requested platform for the session.

    Each is the single place its module asks which platform it is on, which
    is what makes the whole suite coverable from one machine.
    """
    host = request.config.getoption("--cross-platform")
    if not host:
        yield
        return

    import envxx.envvars as envvars
    import envxx.install as install
    import envxx.shims as shims

    saved = {
        "install._host": install._host,
        "shims._is_windows": shims._is_windows,
        "envvars.is_windows": envvars.is_windows,
    }

    install._host = lambda: host
    shims._is_windows = lambda: host == "windows"
    envvars.is_windows = lambda: host == "windows"

    try:
        yield
    finally:
        install._host = saved["install._host"]
        shims._is_windows = saved["shims._is_windows"]
        envvars.is_windows = saved["envvars.is_windows"]
