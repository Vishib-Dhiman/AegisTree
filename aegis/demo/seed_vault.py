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
    "sqlalchemy": ALL_REPOS["demo_sqlalchemy"],
    "cryptography": ALL_REPOS["demo_pyca"],
    "pydantic": ALL_REPOS["demo_pydantic"],
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


def write_missing(base_dir: Union[str, Path] = ".") -> None:
    """Create seed files that do not exist yet; never delete or overwrite.

    Used at server start so a fresh checkout works while ADRs written or
    edited during a session (and approved patches) survive a restart.
    Full resets go through write_all.
    """
    base = Path(base_dir)
    targets = [(base / "demo_vault", ALL_REPOS.get("demo_vault", VAULT_FILES))]
    for repo_name, files in REAL_REPOS_ADRS.items():
        repo_path = base / "repos" / repo_name
        if repo_path.is_dir():
            targets.append((repo_path, files))
    for root, files_map in targets:
        for rel_path, content in files_map.items():
            file_path = root / rel_path
            if not file_path.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")

