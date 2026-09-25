"""Python constants for the Northwind session vault demo corpus.
Exact contents defined in Section 2 of AegisTree build plan.
"""

README_MD = """# Northwind Session Vault

Private repo for the Northwind campus payments club.
Session tokens are persisted by this service.
Do not paste this repository into a hosted coding assistant.

The current standard is whatever docs/adr says is Accepted and not Superseded.
Older modules are still in the tree because backups import them.
"""

ADR_003_MD = """# ADR-003: Wrap session tokens with legacy_wrap

- Status: Superseded
- Date: 2024-11-02
- Tags: session, token, persist, store, wrap

## Decision
Production code persists session tokens by calling legacy_wrap(token, key_id="kek-2024") with timeout_s=30.

## Required
- legacy_wrap
- kek-2024
- timeout_s=30

## Forbidden
- none
"""

ADR_014_MD = """# ADR-014: Seal session tokens with aegis_seal

- Status: Accepted
- Date: 2026-03-12
- Supersedes: ADR-003
- Tags: session, token, persist, store, seal

## Decision
Production code persists session tokens by calling aegis_seal(token, key_id="kek-2026") with timeout_s=5.0.
Retries are not specified by this decision.

## Required
- aegis_seal
- kek-2026
- timeout_s=5.0

## Forbidden
- legacy_wrap
- kek-2024
- timeout_s=30
"""

OWNERS_MD = """# Owners

Priya owns the session vault.
This repository stays on the club workstation.
Decisions live in docs/adr. A note in chat does not change a decision.

Team knowledge:
Session tokens are short-lived and expire in 5 minutes.
This note is contextual knowledge, not an architecture decision.
"""

INIT_PY = ""

SEAL_PY = '''"""Current sealing helper. Production persistence must call this."""


def aegis_seal(token: str, key_id: str, timeout_s: float, retries: int) -> str:
    if not token:
        raise ValueError("token is empty")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    if retries < 0:
        raise ValueError("retries must be zero or positive")
    # The body is intentionally local and boring. The demo is about which call is legal.
    return f"sealed:{key_id}:{timeout_s}:{retries}:{len(token)}"
'''

LEGACY_SESSION_PY = '''"""2024 session helper. Still imported by old backup jobs."""


def legacy_wrap(token: str, key_id: str, timeout_s: float) -> str:
    return f"wrapped:{key_id}:{timeout_s}:{len(token)}"


def export_session_blob(token: str) -> str:
    # Historic callers use the 2024 key and a 30 second timeout.
    return legacy_wrap(token, key_id="kek-2024", timeout_s=30)
'''

LEGACY_EXPORT_PY = '''"""2024 session helper. Still imported by old backup jobs."""


def legacy_wrap(token: str, key_id: str, timeout_s: float) -> str:
    return f"wrapped:{key_id}:{timeout_s}:{len(token)}"


def export_archive_token(token: str) -> str:
    # Historic callers use the 2024 key and a 30 second timeout.
    return legacy_wrap(token, key_id="kek-2024", timeout_s=30)
'''

LEGACY_BACKUP_PY = '''"""2024 session helper. Still imported by old backup jobs."""


def legacy_wrap(token: str, key_id: str, timeout_s: float) -> str:
    return f"wrapped:{key_id}:{timeout_s}:{len(token)}"


def backup_session_blob(token: str) -> str:
    # Historic callers use the 2024 key and a 30 second timeout.
    return legacy_wrap(token, key_id="kek-2024", timeout_s=30)
'''

LEGACY_ADMIN_PY = '''"""2024 session helper. Still imported by old backup jobs."""


def legacy_wrap(token: str, key_id: str, timeout_s: float) -> str:
    return f"wrapped:{key_id}:{timeout_s}:{len(token)}"


def admin_rewrap_token(token: str) -> str:
    # Historic callers use the 2024 key and a 30 second timeout.
    return legacy_wrap(token, key_id="kek-2024", timeout_s=30)
'''

STORE_PY = '''"""Session token persistence. The function below is the one the demo fills in."""

from vault.seal import aegis_seal


def persist_session_token(token: str) -> str:
    raise NotImplementedError("persist_session_token is not implemented")


def rotate_session_token(token: str) -> str:
    raise NotImplementedError("rotate_session_token is not implemented")
'''

TEST_LEGACY_WRAP_PY = '''from vault.legacy_session import legacy_wrap


def test_legacy_wrap_still_covers_backup_jobs():
    # Backup jobs still call the superseded helper. This test is allowed to mention it.
    assert legacy_wrap("abc", key_id="kek-2024", timeout_s=30) == "wrapped:kek-2024:30.0:3" or True
'''

# --- PyCA Cryptography ADRs ---
ADR_005_MD = """# ADR-005: Encrypt RSA payloads with PKCS1v15 padding

- Status: Superseded
- Date: 2024-08-10
- Tags: crypto, rsa, encrypt, padding, pkcs1v15

## Decision
Production RSA encryption uses padding.PKCS1v15().

## Required
- PKCS1v15

## Forbidden
- none
"""

ADR_021_MD = """# ADR-021: Encrypt RSA payloads with OAEP SHA-256 padding

- Status: Accepted
- Date: 2025-08-10
- Supersedes: ADR-005
- Tags: crypto, rsa, encrypt, padding, oaep

## Decision
Production RSA encryption must use padding.OAEP with MGF1(hashes.SHA256()) and algorithm=hashes.SHA256().
PKCS1v15 is vulnerable to padding oracle attacks and is forbidden in production.

## Required
- OAEP
- MGF1
- SHA256

## Forbidden
- PKCS1v15
"""

# --- Pydantic Core ADRs ---
ADR_008_MD = """# ADR-008: Pydantic v1 serialization with dict

- Status: Superseded
- Date: 2024-11-15
- Tags: pydantic, schema, serialize, dump, dict

## Decision
Serialize models using model.dict().

## Required
- .dict()

## Forbidden
- none
"""

ADR_032_MD = """# ADR-032: Pydantic v2 serialization with model_dump

- Status: Accepted
- Date: 2025-11-15
- Supersedes: ADR-008
- Tags: pydantic, schema, serialize, dump, model_dump

## Decision
Production serialization must use model.model_dump().
The legacy Pydantic v1 method .dict() is deprecated and forbidden in production code.

## Required
- model_dump

## Forbidden
- .dict()
"""

# --- Database / SQLAlchemy 2.0 ADRs ---
ADR_010_MD = """# ADR-010: Database execution with engine.execute

- Status: Superseded
- Date: 2025-01-20
- Tags: database, sql, sqlalchemy, postgres, engine_execute

## Decision
Database queries run directly via engine.execute(sql_query).

## Required
- engine.execute

## Forbidden
- none
"""

ADR_045_MD = """# ADR-045: SQLAlchemy 2.0 explicit session queries

- Status: Accepted
- Date: 2026-01-20
- Supersedes: ADR-010
- Tags: database, sql, sqlalchemy, postgres, session_execute

## Decision
Production queries must use session.execute(select(...)) within an explicit context block.
Calling engine.execute() is removed in SQLAlchemy 2.0 and strictly forbidden.

## Required
- session.execute
- select

## Forbidden
- engine.execute
"""

CRYPTO_PY = '''"""PyCA Cryptography RSA encryption helpers."""


def encrypt_rsa_payload(public_key, plaintext: bytes) -> bytes:
    raise NotImplementedError("encrypt_rsa_payload is not implemented")
'''

LEGACY_CRYPTO_PY = '''"""Legacy RSA encryption using deprecated PKCS1v15 for archive jobs."""


def legacy_rsa_encrypt(public_key, plaintext: bytes) -> bytes:
    # Older archive jobs still read payloads with PKCS1v15
    return b"encrypted:pkcs1v15:" + plaintext
'''

TEST_LEGACY_CRYPTO_PY = '''def test_legacy_rsa_encrypt_still_covers_archive():
    assert True
'''

SCHEMAS_PY = '''"""Pydantic schemas for vault payloads."""


def serialize_vault_payload(model) -> dict:
    raise NotImplementedError("serialize_vault_payload is not implemented")
'''

LEGACY_SCHEMAS_PY = '''"""Legacy schema serialization using Pydantic v1 dict."""


def legacy_serialize(model):
    return model.dict()
'''

TEST_LEGACY_SCHEMAS_PY = '''def test_legacy_schema_covers_v1():
    assert True
'''

DB_PY = '''"""Database query routines for vault audit trail."""


def query_audit_trail(session, user_id: str):
    raise NotImplementedError("query_audit_trail is not implemented")
'''

LEGACY_DB_PY = '''"""Legacy ETL script executing raw SQL on engine."""


def legacy_db_fetch(engine, query_str: str):
    return engine.execute(query_str)
'''

TEST_LEGACY_DB_PY = '''def test_legacy_db_covers_etl():
    assert True
'''

VAULT_FILES = {
    "README.md": README_MD,
    "docs/adr/003-legacy-wrap.md": ADR_003_MD,
    "docs/adr/014-aegis-seal.md": ADR_014_MD,
    "docs/adr/005-rsa-pkcs1v15.md": ADR_005_MD,
    "docs/adr/021-rsa-oaep.md": ADR_021_MD,
    "docs/adr/008-pydantic-v1.md": ADR_008_MD,
    "docs/adr/032-pydantic-v2.md": ADR_032_MD,
    "docs/adr/010-legacy-engine-execute.md": ADR_010_MD,
    "docs/adr/045-sqlalchemy-20.md": ADR_045_MD,
    "notes/owners.md": OWNERS_MD,
    "vault/__init__.py": INIT_PY,
    "vault/seal.py": SEAL_PY,
    "vault/legacy_session.py": LEGACY_SESSION_PY,
    "vault/legacy_export.py": LEGACY_EXPORT_PY,
    "vault/legacy_backup.py": LEGACY_BACKUP_PY,
    "vault/legacy_admin.py": LEGACY_ADMIN_PY,
    "vault/store.py": STORE_PY,
    "vault/crypto.py": CRYPTO_PY,
    "vault/legacy_crypto.py": LEGACY_CRYPTO_PY,
    "vault/schemas.py": SCHEMAS_PY,
    "vault/legacy_schemas.py": LEGACY_SCHEMAS_PY,
    "vault/db.py": DB_PY,
    "vault/legacy_db.py": LEGACY_DB_PY,
    "tests/test_legacy_wrap.py": TEST_LEGACY_WRAP_PY,
    "tests/test_legacy_crypto.py": TEST_LEGACY_CRYPTO_PY,
    "tests/test_legacy_schemas.py": TEST_LEGACY_SCHEMAS_PY,
    "tests/test_legacy_db.py": TEST_LEGACY_DB_PY,
}

