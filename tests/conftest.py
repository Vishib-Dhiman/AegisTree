"""Pytest fixtures for AegisTree tests."""

import pytest
from pathlib import Path


@pytest.fixture
def test_vault(tmp_path: Path) -> Path:
    from aegis.demo import seed_vault
    vault_dir = tmp_path / "demo_vault"
    seed_vault.write(vault_dir)
    return vault_dir
