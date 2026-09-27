# Northwind PyCA Cryptography Vault

Microservice handling asymmetric cryptographic payload encryption.
The current standard enforces RSA-OAEP with SHA-256 (ADR-021).
Legacy PKCS1v15 padding (ADR-005) is forbidden in production.
