"""Writes demo repositories from seed constants."""

from pathlib import Path
from typing import Optional, Union
from aegis.demo.seed_content import ALL_REPOS, VAULT_FILES


def write(
    workspace_root: Union[str, Path] = "demo_vault",
    clean_extra: bool = True,
    repo_key: Optional[str] = None
) -> Path:
    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    key = repo_key or root.name
    files_map = ALL_REPOS.get(key, VAULT_FILES)

    if clean_extra:
        # Delete extra ADRs not present in this repo's seed
        adr_dir = root / "docs" / "adr"
        if adr_dir.exists():
            for f in list(adr_dir.glob("*.md")):
                rel = str(f.relative_to(root))
                if rel not in files_map:
                    try:
                        f.unlink()
                    except Exception:
                        pass
        # Delete extra notes not present in this repo's seed
        notes_dir = root / "notes"
        if notes_dir.exists():
            for f in list(notes_dir.glob("*.md")):
                rel = str(f.relative_to(root))
                if rel not in files_map:
                    try:
                        f.unlink()
                    except Exception:
                        pass
        # Delete extra python files in vault/ not present in this repo's seed
        vault_code_dir = root / "vault"
        if vault_code_dir.exists():
            for f in list(vault_code_dir.glob("*.py")):
                rel = str(f.relative_to(root))
                if rel not in files_map:
                    try:
                        f.unlink()
                    except Exception:
                        pass

    for rel_path, content in files_map.items():
        file_path = root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return root


REAL_REPOS_ADRS = {
    "sqlalchemy": {
        "docs/adr/010-legacy-engine-execute.md": ALL_REPOS["demo_sqlalchemy"]["docs/adr/010-legacy-engine-execute.md"],
        "docs/adr/045-sqlalchemy-20.md": ALL_REPOS["demo_sqlalchemy"]["docs/adr/045-sqlalchemy-20.md"],
        "notes/db_standards.md": ALL_REPOS["demo_sqlalchemy"]["notes/db_standards.md"],
        "vault/__init__.py": "",
        "vault/db.py": ALL_REPOS["demo_sqlalchemy"]["vault/db.py"],
        "vault/legacy_db.py": ALL_REPOS["demo_sqlalchemy"]["vault/legacy_db.py"],
    },
    "cryptography": {
        "docs/adr/005-rsa-pkcs1v15.md": ALL_REPOS["demo_pyca"]["docs/adr/005-rsa-pkcs1v15.md"],
        "docs/adr/021-rsa-oaep.md": ALL_REPOS["demo_pyca"]["docs/adr/021-rsa-oaep.md"],
        "notes/crypto_policy.md": ALL_REPOS["demo_pyca"]["notes/crypto_policy.md"],
        "vault/__init__.py": "",
        "vault/crypto.py": ALL_REPOS["demo_pyca"]["vault/crypto.py"],
        "vault/legacy_crypto.py": ALL_REPOS["demo_pyca"]["vault/legacy_crypto.py"],
    },
    "pydantic": {
        "docs/adr/008-pydantic-v1.md": ALL_REPOS["demo_pydantic"]["docs/adr/008-pydantic-v1.md"],
        "docs/adr/032-pydantic-v2.md": ALL_REPOS["demo_pydantic"]["docs/adr/032-pydantic-v2.md"],
        "notes/pydantic_migration.md": ALL_REPOS["demo_pydantic"]["notes/pydantic_migration.md"],
        "vault/__init__.py": "",
        "vault/schemas.py": ALL_REPOS["demo_pydantic"]["vault/schemas.py"],
        "vault/legacy_schemas.py": ALL_REPOS["demo_pydantic"]["vault/legacy_schemas.py"],
    },
}


def sync_real_repos(base_dir: Union[str, Path] = ".") -> None:
    repos_dir = Path(base_dir) / "repos"
    for repo_name, files in REAL_REPOS_ADRS.items():
        repo_path = repos_dir / repo_name
        if repo_path.exists() and repo_path.is_dir():
            for rel_path, content in files.items():
                p = repo_path / rel_path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")


def write_all(base_dir: Union[str, Path] = ".") -> None:
    base = Path(base_dir)
    write(base / "demo_vault", clean_extra=True, repo_key="demo_vault")
    sync_real_repos(base)

