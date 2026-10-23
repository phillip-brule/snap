from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

_kek = None

# How many bytes of the plaintext to encrypt
PREFIX_LEN = 64
# full prefix length: nonce(16) + tag(16) + PREFIX_LEN
SEALED_PREFIX_LEN = PREFIX_LEN + 32

# Read more about functions in docs:
# https://www.pycryptodome.org/src/cipher/modern#crypto-cipher-aes-aesmodecipher-encrypt-and-digest
# and more about AES:
# https://www.pycryptodome.org/src/cipher/aes

def set_kek(kek_path):
    global _kek
    with open(kek_path, "rb") as f:
        _kek = f.read()

def _seal(key, plaintext):
    # nonce (16) + tag (16) + ciphertext — one blob to store
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
    """first PREFIX_LEN bytes; append plaintext tail."""
    dek = get_random_bytes(32)
    prefix, tail = data[:PREFIX_LEN], data[PREFIX_LEN:]
    encrypted_data = _seal(dek, prefix) + tail
    wrapped_dek = _seal(_kek, dek)
    return encrypted_data, wrapped_dek

def decrypt_data(encrypted_data, wrapped_dek):
    dek = _unseal(_kek, wrapped_dek)
    if len(encrypted_data) <= SEALED_PREFIX_LEN:
        return _unseal(dek, encrypted_data)
    sealed = encrypted_data[:SEALED_PREFIX_LEN]
    tail = encrypted_data[SEALED_PREFIX_LEN:]
    return _unseal(dek, sealed) + tail
