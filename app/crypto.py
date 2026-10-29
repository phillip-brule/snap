import hashlib
import hmac

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

_master = None
_file_kek = None
_field_kek = None
_blind_key = None

# How many bytes of the plaintext to encrypt
PREFIX_LEN = 64
# full prefix length: nonce(16) + tag(16) + PREFIX_LEN
SEALED_PREFIX_LEN = PREFIX_LEN + 32

# Read more about functions in docs:
# https://www.pycryptodome.org/src/cipher/modern#crypto-cipher-aes-aesmodecipher-encrypt-and-digest
# and more about AES:
# https://www.pycryptodome.org/src/cipher/aes

def set_kek(kek_path):
    global _master, _file_kek, _field_kek, _blind_key
    with open(kek_path, "rb") as f:
        _master = f.read()
    _file_kek = hmac.new(_master, b"snap-records/file-kek", hashlib.sha256).digest()
    _field_kek = hmac.new(_master, b"snap-records/field-kek", hashlib.sha256).digest()
    _blind_key = hmac.new(_master, b"snap-records/blind-index", hashlib.sha256).digest()


def _seal(key, plaintext):
    cipher = AES.new(key, AES.MODE_GCM)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    return cipher.nonce + tag + ciphertext


def _unseal(key, sealed):
    nonce = sealed[:16]
    tag = sealed[16:32]
    ciphertext = sealed[32:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)


def encrypt_data(data):
    dek = get_random_bytes(32)
    prefix = data[:PREFIX_LEN]
    tail = data[PREFIX_LEN:]
    sealed_prefix = _seal(dek, prefix)
    wrapped_dek = _seal(_file_kek, dek)
    return sealed_prefix + tail, wrapped_dek


def decrypt_data(encrypted_data, wrapped_dek):
    dek = _unseal(_file_kek, wrapped_dek)
    if len(encrypted_data) <= SEALED_PREFIX_LEN:
        return _unseal(dek, encrypted_data)
    sealed = encrypted_data[:SEALED_PREFIX_LEN]
    tail = encrypted_data[SEALED_PREFIX_LEN:]
    prefix = _unseal(dek, sealed)
    return prefix + tail


def encrypt_field(plaintext: bytes) -> bytes:
    return _seal(_field_kek, plaintext)


def decrypt_field(sealed: bytes) -> bytes:
    return _unseal(_field_kek, sealed)


def blind_index(value: str) -> str:
    return hmac.new(_blind_key, value.encode("utf-8"), hashlib.sha256).hexdigest()
