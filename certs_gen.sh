#!/bin/bash
# Creates the SNAP Root CA and a server certificate signed by it (for nginx).
# Import certs/snap-root-ca.crt into your browser/OS trust store to trust the server.
#   usage: ./certs_gen.sh [extra DNS names...]
set -euo pipefail

mkdir -p certs secrets
umask 077

# Root CA (only generated once; re-running reissues the server cert with the same CA)
if [ ! -f secrets/ca.key ]; then
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-384 -out secrets/ca.key
  openssl req -x509 -new -key secrets/ca.key -sha384 -days 1825 \
    -subj "/C=ES/O=SNAP Records/CN=SNAP Records Root CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" \
    -out certs/snap-root-ca.crt
fi

SAN="DNS:localhost,DNS:snap.local,IP:127.0.0.1,IP:::1"
for name in "$@"; do SAN="$SAN,DNS:$name"; done

# Server key + CSR, signed by the Root CA
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out secrets/server.key
openssl req -new -key secrets/server.key -subj "/C=ES/O=SNAP Records/CN=localhost" \
  -out certs/server.csr
openssl x509 -req -in certs/server.csr -CA certs/snap-root-ca.crt -CAkey secrets/ca.key \
  -CAcreateserial -CAserial certs/snap-root-ca.srl -sha256 -days 397 \
  -extfile <(printf "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=%s\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n" "$SAN") \
  -out certs/server.crt
rm certs/server.csr

# Full chain served by nginx (leaf + CA)
cat certs/server.crt certs/snap-root-ca.crt > certs/fullchain.crt
chmod 644 certs/*.crt
chmod 600 secrets/ca.key secrets/server.key

openssl verify -CAfile certs/snap-root-ca.crt certs/server.crt
