# SNAP Records

```bash
./kek_gen.sh      # content encryption master key
./certs_gen.sh    # SNAP Root CA + nginx server certificate (TLS)
docker compose up -d --build
```

Open https://localhost (http://localhost redirects to HTTPS; Flask is no longer exposed on :5000).

To make the browser trust the server, import `certs/snap-root-ca.crt` as a trusted
certificate authority (Firefox: Settings → Certificates → Authorities → Import;
Chrome/Linux: `chrome://certificate-manager` → Custom → Trusted certificates).
Check it from the command line with:

```bash
curl --cacert certs/snap-root-ca.crt -I https://localhost
```


| Email                 | Password     |
| --------------------- | ------------ |
| `admin@snap.records`  | `admin123`   |
| `member@snap.band`    | `member123`  |
| `crew@snap.band`      | `crew123`    |
| `press@example.com`   | `press123`   |
| `fanclub@example.com` | `fanclub123` |
| `fan@example.com`     | `fan123`     |

```bash
docker compose down -v --remove-orphans //for db reset
```

Follow logs:

```bash
docker compose logs -f web
```

Partial-file crypto demo

```bash
head -c 64 file_to_show | xxd
tail -c 12 file_to_show | xxd
docker compose exec web sh -c 'ls /data/uploads/*/*'
docker compose exec web sh -c 'head -c 64 file_to_show | xxd'
docker compose exec web sh -c 'tail -c 12 file_to_show | xxd'
```

Partial DB encryption demo:

```bash
# 1. latest user BEFORE signup
docker compose exec db psql -U snap -d snap_records -c \
  "SELECT display_name, left(encode(email_enc,'hex'),40) AS email_enc_hex, email_hash, created_at FROM users ORDER BY created_at DESC LIMIT 1;"

# 2. follow web logs, then register at /register
docker compose logs -f web

# 3. latest user AFTER signup (match email_hash from the log line)
docker compose exec db psql -U snap -d snap_records -c \
  "SELECT display_name, left(encode(email_enc,'hex'),40) AS email_enc_hex, email_hash, created_at FROM users ORDER BY created_at DESC LIMIT 1;"
```

