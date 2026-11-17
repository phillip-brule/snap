"""Compare full AES-GCM encrypt vs partial (encrypt prefix + AAD over the rest).

Two scenarios:
  A) Our app:     50 MiB file, encrypt first 64 B  (matches PREFIX_LEN in app/crypto.py)
  B) real-ish app: 1 GiB file,  encrypt first 1 MiB

"""
import os
import time

from Crypto.Cipher import AES

ROUNDS = 10


def _bench(label, size, prefix, rounds=ROUNDS):
    print(f"\n=== {label} ===")
    print(
        f"file size={size / (1024 * 1024):.0f} MiB  "
        f"encrypt prefix={prefix:.0f} Bytes  "
        f"rounds={rounds}"
    )
    print("generating file bytes…", flush=True)
    data = os.urandom(size)
    key = os.urandom(32)

    def full():
        c = AES.new(key, AES.MODE_GCM)
        c.encrypt_and_digest(data)

    def partial():
        c = AES.new(key, AES.MODE_GCM)
        c.update(data[prefix:])
        c.encrypt_and_digest(data[:prefix])

    times = {}
    for f in (full, partial):
        print(f"  running {f.__name__}…", flush=True)
        t0 = time.perf_counter()
        for _ in range(rounds):
            f()
        times[f.__name__] = (time.perf_counter() - t0) / rounds
        print(f"  {f.__name__:8s}  {times[f.__name__]:.4f} seconds/file")

    print(f"  speedup   {times['full'] / times['partial']:.2f}x  (full / partial)")
    return times


if __name__ == "__main__":
    _bench("A: Current SNAP", size=50 * 1024 * 1024, prefix=64)

    _bench("B: real-ish app (1 MiB of 1 GiB)", size=1024 * 1024 * 1024, prefix=1024 * 1024)
