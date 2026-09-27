# ADR-021: Encrypt RSA payloads with OAEP SHA-256 padding

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
