"""Writes the Northwind session vault demo repo from seed constants."""

from pathlib import Path
from typing import Union
from aegis.demo.seed_content import VAULT_FILES


def write(workspace_root: Union[str, Path] = "demo_vault", clean_extra: bool = True) -> Path:
    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    if clean_extra:
        # Delete extra ADRs not present in original seed
        adr_dir = root / "docs" / "adr"
        if adr_dir.exists():
            for f in list(adr_dir.glob("*.md")):
                rel = str(f.relative_to(root))
                if rel not in VAULT_FILES:
                    try:
                        f.unlink()
                    except Exception:
                        pass
        # Delete extra notes not present in original seed
        notes_dir = root / "notes"
        if notes_dir.exists():
            for f in list(notes_dir.glob("*.md")):
                rel = str(f.relative_to(root))
                if rel not in VAULT_FILES:
                    try:
                        f.unlink()
                    except Exception:
                        pass
    for rel_path, content in VAULT_FILES.items():
        file_path = root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return root
