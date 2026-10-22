# SNAP Records

```bash
docker compose up -d --build
```

Open http://localhost:5000

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
To follow service:
```bash
docker compose logs -f <service>
```