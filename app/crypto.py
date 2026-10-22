from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

_kek = None

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

def _unseal(key, ciphertext):
    nonce = ciphertext[:16]
    tag = ciphertext[16:32]
    ciphertext = ciphertext[32:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)


def encrypt_data(data):
    dek = get_random_bytes(32)
    return _seal(dek, data), _seal(_kek, dek)

def decrypt_data(encrypted_data, wrapped_dek):
    dek = _unseal(_kek, wrapped_dek)
    return _unseal(dek, encrypted_data)