# SNAP Records

```bash
docker compose up -d --build
```

Open [http://localhost:5000](http://localhost:5000)


| Email                 | Password     |
| --------------------- | ------------ |
| `admin@snap.records`  | `admin123`   |
| `member@snap.band`    | `member123`  |
| `crew@snap.band`      | `crew123`    |
| `press@example.com`   | `press123`   |
| `fanclub@example.com` | `fanclub123` |
| `fan@example.com`     | `fan123`     |


```bash
docker compose down
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

