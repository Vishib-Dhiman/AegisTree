"""Python constants for multi-repository demo corpus and ADR specifications.
Includes complete ADR history with Superseded Rationale / Why Inactive documentation.
"""

README_MD = """# Northwind Session Vault

Private repo for the Northwind campus payments club.
Session tokens are persisted by this service.
Do not paste this repository into a hosted coding assistant.

The current standard is whatever docs/adr says is Accepted and not Superseded.
Older modules are still in the tree because backups import them.
"""

# ==============================================================================
# 1. Northwind Session Vault ADRs (demo_vault)
# ==============================================================================

ADR_001_MD = """# ADR-001: Volatile In-Memory Token Cache

- Status: Superseded
- Date: 2024-03-10
- Tags: session, token, memory, cache, storage

## Decision
Session tokens are stored in volatile process memory in a Python dict without disk persistence or encryption.

## Why Inactive
Process restarts, crashes, and container failovers wiped active user sessions causing payment transaction interruptions. In-memory caching also prohibited horizontal multi-worker scaling across cluster nodes.

## Required
- local_dict_cache

## Forbidden
- none
"""

ADR_003_MD = """# ADR-003: Wrap session tokens with legacy_wrap

- Status: Superseded
- Date: 2024-11-02
- Supersedes: ADR-001
- Tags: session, token, persist, store, wrap

## Decision
Production code persists session tokens by calling legacy_wrap(token, key_id="kek-2024") with timeout_s=30.

## Why Inactive
legacy_wrap relies on a static single-key kek-2024 with a 30s timeout that caused severe database connection pool lockups and failed annual PCI-DSS cryptographic key rotation compliance.

## Required
- legacy_wrap
- kek-2024
- timeout_s=30

## Forbidden
- local_dict_cache
"""

ADR_007_MD = """# ADR-007: Plaintext Token Logging in Audit Events

- Status: Superseded
- Date: 2025-02-14
- Tags: telemetry, logging, audit, security

## Decision
Log raw session tokens in debug and trace logs for operational troubleshooting.

## Why Inactive
Plaintext authentication credentials leaked into centralized logging clusters (Datadog, Elasticsearch), violating GDPR Article 32 and Northwind Club zero-leakage security mandates.

## Required
- log_raw_token

## Forbidden
- none
"""

ADR_014_MD = """# ADR-014: Persist and seal session tokens with aegis_seal

- Status: Accepted
- Date: 2026-03-12
- Supersedes: ADR-003
- Tags: session, token, persist, store, stored, stores, seal

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

ADR_018_MD = """# ADR-018: Masked Session Token Telemetry

- Status: Accepted
- Date: 2026-03-20
- Supersedes: ADR-007
- Tags: telemetry, logging, privacy, masking, audit

## Decision
All audit logs and telemetry emitters must sanitize tokens with mask_token_signature(token), outputting only the prefix and a SHA-256 fingerprint.

## Required
- mask_token_signature

## Forbidden
- log_raw_token
- print(token)
"""

ADR_025_MD = """# ADR-025: Strict 300s Session TTL and Nonce Verification

- Status: Accepted
- Date: 2026-04-01
- Tags: session, auth, nonce, timeout, security

## Decision
Enforce a strict 300-second session time-to-live. Re-issuance requires a cryptographically validated nonce challenge via validate_session_nonce(nonce).

## Required
- validate_session_nonce
- session_ttl=300

## Forbidden
- infinite_ttl
- skip_nonce_check
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

# ==============================================================================
# 2. PyCA Cryptography ADRs (repos/cryptography)
# ==============================================================================

ADR_002_MD = """# ADR-002: RSA Digital Signatures with SHA-1

- Status: Superseded
- Date: 2024-04-10
- Tags: crypto, rsa, signature, sha1, digest

## Decision
Generate cryptographic digital signatures using RSA with SHA-1 message digests (hashes.SHA1()).

## Why Inactive
SHA-1 is cryptographically broken due to practical collision attacks (SHAttered) and is explicitly disallowed by NIST SP 800-131A and FIPS 140-3.

## Required
- hashes.SHA1()

## Forbidden
- none
"""

ADR_005_MD = """# ADR-005: Encrypt RSA payloads with PKCS1v15 padding

- Status: Superseded
- Date: 2024-08-10
- Tags: crypto, rsa, encrypt, padding, pkcs1v15

## Decision
Production RSA encryption uses padding.PKCS1v15().

## Why Inactive
PKCS#1 v1.5 padding is susceptible to Bleichenbacher padding oracle attacks and deterministic chosen-ciphertext exploitation.

## Required
- PKCS1v15

## Forbidden
- none
"""

ADR_009_MD = """# ADR-009: Stream Encryption with ARC4

- Status: Superseded
- Date: 2024-12-05
- Tags: crypto, stream, cipher, arc4, symmetric

## Decision
High-throughput bulk encryption of temporary cache streams utilizes ARC4 (RC4) cipher.

## Why Inactive
ARC4 contains fundamental statistical biases in its keystream output (RFC 7465, Bar Mitzvah attack). Prohibited in all secure communication protocols.

## Required
- algorithms.ARC4

## Forbidden
- none
"""

ADR_015_MD = """# ADR-015: Enforce SHA-256 Minimum for Cryptographic Hashes

- Status: Accepted
- Date: 2025-06-15
- Supersedes: ADR-002
- Tags: crypto, hash, digest, sha256, sha512

## Decision
All cryptographic signatures and hash computations must use a minimum security strength of SHA-256 (hashes.SHA256()) or SHA-512.

## Required
- hashes.SHA256()

## Forbidden
- hashes.SHA1()
- hashes.MD5()
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

ADR_027_MD = """# ADR-027: Authenticated Symmetric Encryption with AES-GCM

- Status: Accepted
- Date: 2025-11-20
- Supersedes: ADR-009
- Tags: crypto, symmetric, aes, gcm, aead

## Decision
All symmetric payload encryption must utilize AES-GCM (AESGCM(key)) with a fresh 12-byte random initialization nonce (os.urandom(12)). Unauthenticated cipher modes like ECB or plain CBC are strictly forbidden.

## Required
- AESGCM
- os.urandom(12)

## Forbidden
- algorithms.ARC4
- modes.ECB
"""

ADR_035_MD = """# ADR-035: Asymmetric Identity Signatures with Ed25519

- Status: Accepted
- Date: 2026-02-15
- Tags: crypto, ed25519, identity, curve25519, signing

## Decision
Service identity exchange and microservice handshakes must employ Ed25519 digital signatures (Ed25519PrivateKey.generate()).

## Required
- Ed25519PrivateKey
- Ed25519PublicKey

## Forbidden
- dsa.DSAPrivateKey
"""

# ==============================================================================
# 3. Pydantic Core ADRs (repos/pydantic)
# ==============================================================================

ADR_004_MD = """# ADR-004: Model Pre-Validation with root_validator

- Status: Superseded
- Date: 2024-05-18
- Tags: pydantic, validation, root_validator, pre

## Decision
Cross-field model normalization and sanitization is implemented using @root_validator(pre=True).

## Why Inactive
@root_validator was deprecated in Pydantic v2 and incurs significant Python-level overhead. Replaced by Rust-native @model_validator(mode='before').

## Required
- root_validator(pre=True)

## Forbidden
- none
"""

ADR_008_MD = """# ADR-008: Pydantic v1 serialization with dict

- Status: Superseded
- Date: 2024-11-15
- Tags: pydantic, schema, serialize, dump, dict

## Decision
Serialize models using model.dict().

## Why Inactive
model.dict() and model.json() are legacy Pydantic v1 methods deprecated in v2. They lack serialization plugins and performance benefits of pydantic-core.

## Required
- .dict()

## Forbidden
- none
"""

ADR_012_MD = """# ADR-012: Model Construction with parse_obj

- Status: Superseded
- Date: 2025-01-10
- Tags: pydantic, instantiation, parse_obj, factory

## Decision
Construct Pydantic model instances from external payload dictionaries using Model.parse_obj(data).

## Why Inactive
parse_obj was deprecated in Pydantic v2 in favor of Model.model_validate(data), which integrates directly into pydantic-core's validation graph.

## Required
- parse_obj

## Forbidden
- none
"""

ADR_029_MD = """# ADR-029: Model Validation with model_validator

- Status: Accepted
- Date: 2025-09-01
- Supersedes: ADR-004
- Tags: pydantic, validation, model_validator, core

## Decision
Cross-field validation must use @model_validator(mode="before") or @model_validator(mode="after"). The legacy decorator @root_validator is forbidden.

## Required
- model_validator
- mode=

## Forbidden
- root_validator
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
- .json()
"""

ADR_036_MD = """# ADR-036: Model Instantiation via model_validate

- Status: Accepted
- Date: 2026-01-12
- Supersedes: ADR-012
- Tags: pydantic, validation, model_validate, parse

## Decision
All dictionary-to-model conversions and parsing must execute via Model.model_validate(payload) or Model.model_validate_json(raw_json).

## Required
- model_validate

## Forbidden
- parse_obj
- parse_raw
"""

ADR_041_MD = """# ADR-041: Explicit Field Validation and Serialization Aliases

- Status: Accepted
- Date: 2026-03-05
- Tags: pydantic, schema, alias, serialization_alias

## Decision
Wire schemas requiring camelCase transformation must define Field(validation_alias=..., serialization_alias=...) explicitly.

## Required
- Field
- serialization_alias

## Forbidden
- allow_population_by_field_name
"""

# ==============================================================================
# 4. Database / SQLAlchemy 2.0 ADRs (repos/sqlalchemy)
# ==============================================================================

ADR_006_MD = """# ADR-006: Raw String SQL Concatenation

- Status: Superseded
- Date: 2024-06-12
- Tags: database, sql, raw_query, injection

## Decision
Execute ad-hoc database queries using string formatted SQL directly via connection.execute("SELECT ... WHERE id = " + id).

## Why Inactive
Raw string query interpolation exposed endpoints to catastrophic SQL injection attacks and bypassed query caching and dial-in type mapping.

## Required
- connection.execute

## Forbidden
- none
"""

ADR_010_MD = """# ADR-010: Database execution with engine.execute

- Status: Superseded
- Date: 2025-01-20
- Tags: database, sql, sqlalchemy, postgres, engine_execute

## Decision
Database queries run directly via engine.execute(sql_query).

## Why Inactive
Connectionless execution via engine.execute() was permanently removed in SQLAlchemy 2.0. It broke connection pooling boundaries and transaction scopes.

## Required
- engine.execute

## Forbidden
- none
"""

ADR_016_MD = """# ADR-016: ORM Queries with session.query

- Status: Superseded
- Date: 2025-04-18
- Tags: database, orm, query, legacy

## Decision
ORM entity querying uses the SQLAlchemy 1.x Query object pattern (session.query(Model).filter(...).all()).

## Why Inactive
The 1.x session.query() interface is legacy and superseded in SQLAlchemy 2.0 by the 2.0 style select() construct with session.scalars().

## Required
- session.query

## Forbidden
- none
"""

ADR_022_MD = """# ADR-022: Parameterized SQL with text() Constructs

- Status: Accepted
- Date: 2025-07-22
- Supersedes: ADR-006
- Tags: database, sql, text, bind_params, security

## Decision
All textual SQL statements must be wrapped in text(...) with named bind parameters (:param_name) and passed as a mapping dictionary.

## Required
- text
- params=

## Forbidden
- connection.execute(f"
- engine.execute(f"
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

ADR_048_MD = """# ADR-048: Unified 2.0 ORM Queries with session.scalars

- Status: Accepted
- Date: 2026-02-10
- Supersedes: ADR-016
- Tags: database, orm, select, scalars, sqlalchemy20

## Decision
ORM query execution must use session.scalars(select(Model).where(...)).all() to retrieve model entities. The legacy session.query construct is forbidden.

## Required
- session.scalars
- select

## Forbidden
- session.query
"""

ADR_052_MD = """# ADR-052: Async Database Operations with AsyncSession

- Status: Accepted
- Date: 2026-03-01
- Tags: database, async, asyncio, async_session, postgres

## Decision
Asynchronous FastAPI endpoints must execute database I/O using AsyncSession obtained from async_sessionmaker(engine, expire_on_commit=False).

## Required
- AsyncSession
- async_sessionmaker
- expire_on_commit=False

## Forbidden
- threading.local
"""

# ==============================================================================
# Code stubs & test files
# ==============================================================================

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

# 1. Northwind Session Vault (demo_vault)
VAULT_FILES = {
    "README.md": README_MD,
    "docs/adr/001-in-memory-token-cache.md": ADR_001_MD,
    "docs/adr/003-legacy-wrap.md": ADR_003_MD,
    "docs/adr/007-raw-token-logging.md": ADR_007_MD,
    "docs/adr/014-aegis-seal.md": ADR_014_MD,
    "docs/adr/018-masked-token-telemetry.md": ADR_018_MD,
    "docs/adr/025-ephemeral-session-ttl.md": ADR_025_MD,
    "notes/owners.md": OWNERS_MD,
    "vault/__init__.py": INIT_PY,
    "vault/seal.py": SEAL_PY,
    "vault/store.py": STORE_PY,
    "vault/legacy_session.py": LEGACY_SESSION_PY,
    "vault/legacy_export.py": LEGACY_EXPORT_PY,
    "vault/legacy_backup.py": LEGACY_BACKUP_PY,
    "vault/legacy_admin.py": LEGACY_ADMIN_PY,
    "tests/test_legacy_wrap.py": TEST_LEGACY_WRAP_PY,
}

# 2. PyCA Cryptography Microservice (demo_pyca / repos/cryptography)
PYCA_README = """# Northwind PyCA Cryptography Vault

Microservice handling asymmetric cryptographic payload encryption.
The current standard enforces RSA-OAEP with SHA-256 (ADR-021).
Legacy PKCS1v15 padding (ADR-005) and SHA-1 (ADR-002) are forbidden in production.
"""

PYCA_NOTE_MD = """# Cryptographic Policy & Standards

All asymmetric payload encryption must use RSA-OAEP with SHA-256.
PKCS1v15 padding and SHA-1 signatures are prohibited across all production endpoints.
"""

PYCA_FILES = {
    "README.md": PYCA_README,
    "docs/adr/002-sha1-signatures.md": ADR_002_MD,
    "docs/adr/005-rsa-pkcs1v15.md": ADR_005_MD,
    "docs/adr/009-arc4-stream-cipher.md": ADR_009_MD,
    "docs/adr/015-enforce-sha256-minimum.md": ADR_015_MD,
    "docs/adr/021-rsa-oaep.md": ADR_021_MD,
    "docs/adr/027-aes-gcm-authenticated-encryption.md": ADR_027_MD,
    "docs/adr/035-ed25519-asymmetric-identities.md": ADR_035_MD,
    "notes/crypto_policy.md": PYCA_NOTE_MD,
    "vault/__init__.py": INIT_PY,
    "vault/crypto.py": CRYPTO_PY,
    "vault/legacy_crypto.py": LEGACY_CRYPTO_PY,
    "tests/test_legacy_crypto.py": TEST_LEGACY_CRYPTO_PY,
}

# 3. Pydantic Serialization Vault (demo_pydantic / repos/pydantic)
PYDANTIC_README = """# Northwind Schema Registry

Microservice for data serialization and API payload schemas.
The current standard enforces Pydantic v2 model_dump() (ADR-032).
Legacy Pydantic v1 .dict() calls (ADR-008) are deprecated and forbidden.
"""

PYDANTIC_NOTE_MD = """# Pydantic v2 Migration Guide

Migration from v1 (.dict()) to v2 (model_dump()) completed.
Direct model.dict(), parse_obj(), and root_validator usage are forbidden in production.
"""

PYDANTIC_FILES = {
    "README.md": PYDANTIC_README,
    "docs/adr/004-root-validator-pre.md": ADR_004_MD,
    "docs/adr/008-pydantic-v1.md": ADR_008_MD,
    "docs/adr/012-parse-obj-factory.md": ADR_012_MD,
    "docs/adr/029-model-validator-modes.md": ADR_029_MD,
    "docs/adr/032-pydantic-v2.md": ADR_032_MD,
    "docs/adr/036-model-validate-instantiation.md": ADR_036_MD,
    "docs/adr/041-field-serialization-alias.md": ADR_041_MD,
    "notes/pydantic_migration.md": PYDANTIC_NOTE_MD,
    "vault/__init__.py": INIT_PY,
    "vault/schemas.py": SCHEMAS_PY,
    "vault/legacy_schemas.py": LEGACY_SCHEMAS_PY,
    "tests/test_legacy_schemas.py": TEST_LEGACY_SCHEMAS_PY,
}

# 4. SQLAlchemy 2.0 Database Vault (demo_sqlalchemy / repos/sqlalchemy)
SQLALCHEMY_README = """# Northwind Database Audit Service

Service for querying transactional audit logs.
The current standard enforces SQLAlchemy 2.0 explicit session queries (ADR-045).
Direct engine.execute() calls (ADR-010) and session.query() (ADR-016) are strictly forbidden.
"""

SQLALCHEMY_NOTE_MD = """# Database Architecture Standards

SQLAlchemy 2.0 enforces 2.0-style execution: session.execute(select(...)) and session.scalars(select(...)).
Direct calls to engine.execute() and raw string SQL concatenation are removed and forbidden.
"""

SQLALCHEMY_FILES = {
    "README.md": SQLALCHEMY_README,
    "docs/adr/006-raw-string-sql-execution.md": ADR_006_MD,
    "docs/adr/010-legacy-engine-execute.md": ADR_010_MD,
    "docs/adr/016-query-object-api.md": ADR_016_MD,
    "docs/adr/022-parameterized-text-queries.md": ADR_022_MD,
    "docs/adr/045-sqlalchemy-20.md": ADR_045_MD,
    "docs/adr/048-unified-select-orm-queries.md": ADR_048_MD,
    "docs/adr/052-async-session-concurrency.md": ADR_052_MD,
    "notes/db_standards.md": SQLALCHEMY_NOTE_MD,
    "vault/__init__.py": INIT_PY,
    "vault/db.py": DB_PY,
    "vault/legacy_db.py": LEGACY_DB_PY,
    "tests/test_legacy_db.py": TEST_LEGACY_DB_PY,
}

ALL_REPOS = {
    "demo_vault": VAULT_FILES,
    "demo_pyca": PYCA_FILES,
    "demo_pydantic": PYDANTIC_FILES,
    "demo_sqlalchemy": SQLALCHEMY_FILES,
}
