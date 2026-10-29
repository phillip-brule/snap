# Architecture

## Overview

SNAP Records is planned as a small containerized web stack. **Design phase only** — components below are target architecture, not deployed yet.

**In scope when building:** Nginx (optional early; required for TLS later), Flask app, PostgreSQL, file volume.

**Access control:** AuthzForce XACML 3.0 PDP (see [ACCESS_CONTROL.md](ACCESS_CONTROL.md)).

## Component diagram

```mermaid
flowchart TB
  subgraph clients [Clients]
    Browser[Browser]
  end

  subgraph edge [Edge]
    Nginx[Nginx_reverse_proxy]
  end

  subgraph app [Application]
    Flask[Flask_web_app]
    Policy[can_access_policy]
  end

  subgraph data [Data]
    PG[(PostgreSQL)]
    Vol[File_volume]
  end

  subgraph authz [Access_control]
    Authz[AuthzForce_XACML_PDP]
  end

  subgraph deferred [Deferred_security]
    Secrets[Docker_secrets]
    OAuth[OAuth_OIDC_IdP]
  end

  Browser --> Nginx
  Nginx --> Flask
  Flask --> Policy
  Flask --> PG
  Flask --> Vol
  Policy -->|XACML| Authz
  Flask -.->|later| Secrets
  Flask -.->|later| OAuth
```

## Responsibilities

| Component | Responsibility |
|-----------|----------------|
| Nginx | Terminate TLS with a certificate signed by the SNAP Root CA (`certs_gen.sh`), redirect HTTP→HTTPS, HSTS and security headers, forward HTTP to Flask |
| Flask | Pages, forms, session auth, upload/download, permission UI, access logging, in-app authorization |
| `can_access` | Single policy entrypoint (PEP/PIP): gathers role, membership, audience, time window and grant attributes and asks the XACML PDP |
| PostgreSQL | Label, bands, users, memberships, invitations, content metadata, grants, access logs. Later: wrapped file keys, encrypted fields |
| File volume | Stored content blobs. Later: ciphertext only |
| AuthzForce | XACML 3.0 PDP/PAP evaluating `authz/snap-policy.xml`; internal network only |
| Docker secrets | Deferred master keys, DB credentials, OAuth client secret |
| OAuth / OIDC | Deferred fan Google login |

## Request flow (authenticated content access)

```mermaid
sequenceDiagram
  participant U as User
  participant N as Nginx
  participant F as Flask
  participant P as can_access
  participant DB as PostgreSQL
  participant FS as FileVolume

  U->>N: GET content or download
  N->>F: proxy request
  F->>DB: load user memberships and item
  F->>P: can_access user item action
  alt allowed
    P-->>F: allow
    F->>DB: insert access_log allowed
    F->>FS: read file if download or stream
    F-->>U: content or file
  else denied
    P-->>F: deny
    F->>DB: insert access_log denied
    F-->>U: 403
  end
```

## Deployment sketch (Phase 2+)

Suggested layout when implementation starts (not created in design phase):

```text
project/
  docs/                 # design (exists)
  app/                  # Flask package
  migrations/           # DB migrations
  docker-compose.yml    # web, db, volume; nginx later
  .env.example          # non-secret defaults
```

Single label means no tenant router and no per-label DB. One PostgreSQL database; one `labels` row: SNAP Records.

## Trust boundaries (for later security work)

```mermaid
flowchart LR
  Internet[Internet] -->|HTTPS| DMZ[Nginx]
  DMZ -->|HTTP_internal| App[Flask]
  App --> DB[(PostgreSQL)]
  App --> Files[Volume]
  App -->|XACML_request| PDP[AuthzForce]
```

Until Phase 3, treat the app as a local/dev service with simple auth. Do not claim production-hardening.

## Related docs

- [PLAN.md](PLAN.md) — roadmap and deferred features  
- [DATA_MODEL.md](DATA_MODEL.md) — what PostgreSQL stores  
- [ACCESS_CONTROL.md](ACCESS_CONTROL.md) — policy rules behind `can_access`  
