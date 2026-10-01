"""Pytest fixtures for AegisTree tests."""

import pytest
from pathlib import Path


@pytest.fixture
def test_vault(tmp_path: Path) -> Path:
    from aegis.demo import seed_vault
    vault_dir = tmp_path / "demo_vault"
    seed_vault.write(vault_dir)
    return vault_dir


_exit_status = 0


def pytest_sessionfinish(session, exitstatus):
    global _exit_status
    _exit_status = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    # torch and the other native libraries loaded here (CTranslate2, onnxruntime) register
    # teardown that can race at interpreter exit (libc++ "recursive_mutex lock failed").
    # Every report has been written by now, so leave without running it.
    import os
    import sys
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_exit_status)
