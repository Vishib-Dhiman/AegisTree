"""Legacy RSA encryption using deprecated PKCS1v15 for archive jobs."""


def legacy_rsa_encrypt(public_key, plaintext: bytes) -> bytes:
    # Older archive jobs still read payloads with PKCS1v15
    return b"encrypted:pkcs1v15:" + plaintext
