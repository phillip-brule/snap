#!/bin/bash
mkdir -p secrets
openssl rand -out secrets/content_kek 32
chmod 600 secrets/content_kek