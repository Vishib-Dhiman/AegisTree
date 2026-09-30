from pathlib import Path

from aegis.demo import seed_vault


def test_write_missing_creates_seed_but_keeps_session_changes(tmp_path: Path):
    seed_vault.write_missing(tmp_path)
    adr_dir = tmp_path / "demo_vault" / "docs" / "adr"
    seeded = adr_dir / "014-aegis-seal.md"
    assert seeded.exists()

    added = adr_dir / "030-admin-theming.md"
    added.write_text("# ADR-030: Admin theming\n- Status: Accepted\n")
    seeded.write_text(seeded.read_text() + "\nEdited during the session.\n")
    (adr_dir / "025-ephemeral-session-ttl.md").unlink()

    seed_vault.write_missing(tmp_path)
    assert added.exists()
    assert "Edited during the session." in seeded.read_text()
    assert (adr_dir / "025-ephemeral-session-ttl.md").exists()  # missing file restored


def test_write_all_still_resets(tmp_path: Path):
    seed_vault.write_missing(tmp_path)
    added = tmp_path / "demo_vault" / "docs" / "adr" / "030-admin-theming.md"
    added.write_text("# ADR-030: Admin theming\n")
    seed_vault.write_all(tmp_path)
    assert not added.exists()
