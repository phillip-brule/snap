import hashlib
import hmac

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

_file_kek = None
_db_field_key = None
_blind_key = None

# How many bytes of the plaintext to encrypt
PREFIX_LEN = 64
# full prefix length: nonce(16) + tag(16) + PREFIX_LEN
SEALED_PREFIX_LEN = PREFIX_LEN + 32

# secrets/content_kek layout: 3 × 32-byte random keys (no derivation)
_KEY_LEN = 32
_BUNDLE_LEN = _KEY_LEN * 3

# Read more about functions in docs:
# https://www.pycryptodome.org/src/cipher/modern#crypto-cipher-aes-aesmodecipher-encrypt-and-digest
# and more about AES:
# https://www.pycryptodome.org/src/cipher/aes


def set_kek(kek_path):
    """Load three independent random keys from the Docker secret file."""
    global _file_kek, _db_field_key, _blind_key
    with open(kek_path, "rb") as f:
        bundle = f.read()
    if len(bundle) != _BUNDLE_LEN:
        raise ValueError(
            f"content_kek must be {_BUNDLE_LEN} random bytes "
            f"(file_kek + db_field_key + blind_index); got {len(bundle)}"
        )
    _file_kek = bundle[0:_KEY_LEN]
    _db_field_key = bundle[_KEY_LEN : _KEY_LEN * 2]
    _blind_key = bundle[_KEY_LEN * 2 : _KEY_LEN * 3]


def _seal(key, plaintext, aad=b""):
    cipher = AES.new(key, AES.MODE_GCM)
    if aad:
        cipher.update(aad)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    return cipher.nonce + tag + ciphertext


def _unseal(key, sealed, aad=b""):
    nonce = sealed[:16]
    tag = sealed[16:32]
    ciphertext = sealed[32:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    if aad:
        cipher.update(aad)
    return cipher.decrypt_and_verify(ciphertext, tag)


def encrypt_data(data):
    """Partial encrypt (prefix only) + full-file auth (tail bound as GCM AAD)."""
    dek = get_random_bytes(32)
    prefix = data[:PREFIX_LEN]
    tail = data[PREFIX_LEN:]
    sealed_prefix = _seal(dek, prefix, aad=tail)
    wrapped_dek = _seal(_file_kek, dek)
    return sealed_prefix + tail, wrapped_dek


def decrypt_data(encrypted_data, wrapped_dek):
    dek = _unseal(_file_kek, wrapped_dek)
    if len(encrypted_data) <= SEALED_PREFIX_LEN:
        return _unseal(dek, encrypted_data)
    sealed = encrypted_data[:SEALED_PREFIX_LEN]
    tail = encrypted_data[SEALED_PREFIX_LEN:]
    prefix = _unseal(dek, sealed, aad=tail)
    return prefix + tail


def encrypt_field(plaintext: bytes) -> bytes:
    return _seal(_db_field_key, plaintext)


def decrypt_field(sealed: bytes) -> bytes:
    return _unseal(_db_field_key, sealed)


def blind_index(value: str) -> str:
    return hmac.new(_blind_key, value.encode("utf-8"), hashlib.sha256).hexdigest()
