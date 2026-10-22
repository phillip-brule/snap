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

| Email | Password |
|-------|----------|
| `admin@snap.records` | `admin123` |
| `member@snap.band` | `member123` |
| `crew@snap.band` | `crew123` |
| `press@example.com` | `press123` |
| `fanclub@example.com` | `fanclub123` |
| `fan@example.com` | `fan123` |

```bash
docker compose down
```
