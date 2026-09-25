"""Writes the Northwind session vault demo repo from seed constants."""

from pathlib import Path
from typing import Union
from aegis.demo.seed_content import VAULT_FILES


def write(workspace_root: Union[str, Path] = "demo_vault") -> Path:
    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    for rel_path, content in VAULT_FILES.items():
        file_path = root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return root
