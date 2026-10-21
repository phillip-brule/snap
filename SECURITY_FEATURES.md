# SNAP Records — Security Features Quick Guide

This guide explains how to run and test the two implemented security features: **Google OAuth 2.0 / OpenID Connect** and **Recipient Watermarking with Audit Logging**.

## 1. Start the application

From the project directory:

```bash
docker compose up -d --build
```

Check that the containers are running:

```bash
docker compose ps
```

Open the application at:

http://localhost:5000

To inspect application logs:

```bash
docker compose logs web --tail=50
```

## 2. Google OAuth Login

Google authentication is implemented using Authlib and OpenID Connect.

Create or update the local `.env` file with the following settings:

```env
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
FLASK_SECRET_KEY=your_random_secret_key
```

Configure the following authorized redirect URI in Google Cloud Console:

```text
http://localhost:5000/auth/google/callback
```

Restart the application after updating the configuration:

```bash
docker compose up -d --force-recreate web
```

**Testing:**

1. Open http://localhost:5000.
2. Click **Continue with Google** on the login page.
3. Sign in with an authorized Google account.
4. New Google users should receive the `registered` role by default.

Existing user roles and access permissions are preserved.

## 3. Recipient Watermarking

Personalized watermarks are automatically generated when an authorized user downloads a supported file.

**Supported formats:** JPG, PNG, PDF.

**How to test:**

1. Sign in to SNAP Records.
2. Open a file that your account is permitted to download.
3. Click **Download**.
4. Open the downloaded file and inspect its watermark.

Example watermark:

```text
SNAP Records | User: 7fff0623 | Copy: 62c6c5457b9f32a9
```

Each download receives a new Copy ID. Original files remain unchanged.

MP3 and MP4 watermarking are not implemented.

## 4. Verify the Audit Trail

Each successfully generated watermarked download is registered in the PostgreSQL table `watermark_downloads`.

List the latest downloads:

```bash
docker compose exec db psql -U snap -d snap_records -c "SELECT w.download_id, u.email, c.title, w.watermark_type, w.created_at FROM watermark_downloads w JOIN users u ON u.id = w.user_id JOIN content_items c ON c.id = w.content_id ORDER BY w.created_at DESC LIMIT 10;"
```

Find the recipient of a specific copy:

```bash
docker compose exec db psql -U snap -d snap_records -c "SELECT u.email, c.title, w.created_at FROM watermark_downloads w JOIN users u ON u.id = w.user_id JOIN content_items c ON c.id = w.content_id WHERE w.download_id = 'YOUR_COPY_ID';"
```

Replace `YOUR_COPY_ID` with the identifier visible in the watermarked file.

The database can identify which user account received a particular generated copy.

## 5. Troubleshooting

Check the application logs:

```bash
docker compose logs web --tail=100
```

Check whether the watermark module is available:

```bash
docker compose exec web python -c "from app.watermark import SUPPORTED_TYPES; print(SUPPORTED_TYPES)"
```

Check whether the audit table exists:

```bash
docker compose exec db psql -U snap -d snap_records -c "\d watermark_downloads"
```

If changes are not applied, rebuild the web container:

```bash
docker compose up -d --build web
```

## 6. Security Notes

- Never commit `.env`, Google Client Secrets, or Flask secret keys.
- Google OAuth requires valid credentials and an authorized redirect URI.
- Google test accounts must be permitted by the Google Cloud OAuth configuration when the app is in Testing mode.
- Watermarking applies only after the existing download authorization check.
- Each Copy ID is stored with the associated user and content record.
- The audit records issuance of a personalized copy, not proof that the browser completed its download.
- Watermarks provide traceability but are not tamper-proof DRM.

## Implementation Files

| File | Purpose |
|---|---|
| `app/routes/auth.py` | Google OAuth login and callback |
| `app/__init__.py` | OAuth initialization |
| `app/models.py` | OAuth identity and watermark audit models |
| `app/routes/content.py` | Watermarked download handling |
| `app/watermark.py` | JPG, PNG and PDF watermark generation |
| `app/templates/auth/login.html` | Google login button |
| `docker-compose.yml` | Environment configuration |
| `requirements.txt` | Python dependencies |

**Implemented features:** Google OAuth / OpenID Connect and Recipient Watermarking with PostgreSQL Audit Trail.