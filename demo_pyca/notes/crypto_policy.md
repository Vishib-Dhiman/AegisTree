# Cryptographic Policy & Standards

All asymmetric payload encryption must use RSA-OAEP with SHA-256.
PKCS1v15 padding is prohibited across all production endpoints due to padding oracle vulnerabilities.
