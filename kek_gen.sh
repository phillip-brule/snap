#!/bin/bash
# Three independent 32-byte random keys in one Docker secret:
#   file_kek (wraps file DEKs) | db_field_key (DB columns) | blind_index key
mkdir -p secrets
openssl rand -out secrets/content_kek 96
chmod 600 secrets/content_kek
echo "wrote secrets/content_kek (96 bytes: file_kek + db_field_key + blind_index)"
