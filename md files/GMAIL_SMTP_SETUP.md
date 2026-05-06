# 📧 Gmail SMTP Setup for EnviroNode

**Status:** Updated to use real Gmail SMTP instead of console backend

---

## Quick Setup

### Step 1: Enable 2-Factor Authentication (Gmail Account)
Visit: https://myaccount.google.com/security
- Enable 2-Step Verification
- Complete verification

### Step 2: Generate App Password
Visit: https://myaccount.google.com/apppasswords
- Select: Mail + Windows Computer
- Google generates 16-character password
- Copy it

### Step 3: Set Environment Variables

**Windows (CMD):**
```cmd
setx EMAIL_HOST_USER "your-email@gmail.com"
setx EMAIL_HOST_PASSWORD "your-16-char-password"
setx FRONTEND_BASE_URL "http://127.0.0.1:8000"
```

**Windows (PowerShell):**
```powershell
$env:EMAIL_HOST_USER = "rodriguezluisgab@gmail.com"
$env:EMAIL_HOST_PASSWORD = "lkxh odyj yeop kjgc"
$env:FRONTEND_BASE_URL = "http://127.0.0.1:8000"
```

**Linux/Mac (.bashrc or .bash_profile):**
```bash
export EMAIL_HOST_USER="environodeembo@gmail.com"
export EMAIL_HOST_PASSWORD="difr zuby apyb hmvw"
export FRONTEND_BASE_URL="http://127.0.0.1:8000"
```

### Step 4: Restart Django Server
```bash
python manage.py runserver
```

---

## Environment Variables

| Variable | Example | Purpose |
|----------|---------|---------|
| `EMAIL_HOST_USER` | `admin@gmail.com` | Gmail address (required) |
| `EMAIL_HOST_PASSWORD` | `abcd efgh ijkl mnop` | App password from Gmail (required) |
| `FRONTEND_BASE_URL` | `http://127.0.0.1:8000` | Base URL for activation links (optional, defaults to localhost) |

---

## Frontend Base URL Examples

Set `FRONTEND_BASE_URL` for different environments:

```bash
# Development
FRONTEND_BASE_URL="http://127.0.0.1:8000"

# Ngrok (for testing with real email)
FRONTEND_BASE_URL="https://xxxx-xx-xxx-xxx-xx.ngrok.io"

# Production (Render, Heroku, etc.)
FRONTEND_BASE_URL="https://yourdomain.com"
```

---

## Testing Email

### Test 1: Verify Variables Are Set
```bash
# Windows
echo %EMAIL_HOST_USER%
echo %EMAIL_HOST_PASSWORD%
echo %FRONTEND_BASE_URL%

# Linux/Mac
echo $EMAIL_HOST_USER
echo $EMAIL_HOST_PASSWORD
echo $FRONTEND_BASE_URL
```

### Test 2: Send Invitation
1. Go to `/dashboard/users/`
2. Click "Invite User"
3. Fill in form, click "Send Invitation"
4. Check Gmail inbox (should arrive in 5-10 seconds)

### Test 3: Verify Activation Link
1. Copy the activation link from email
2. Verify domain matches FRONTEND_BASE_URL
3. Example: `http://127.0.0.1:8000/activate/MzY=/token-abc123xyz/`
4. Click link → Password setup form should appear

### Test 4: Complete Activation
1. Set password (min 8 chars)
2. Click "Activate Account"
3. Should auto-login to dashboard

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Emails not sending | Check env vars are set: `echo $EMAIL_HOST_USER` |
| "Invalid credentials" error | Verify app password (not account password) |
| Activation links broken | Check FRONTEND_BASE_URL matches your actual domain |
| Email appears in spam | Add SPF/DKIM records for your domain (production only) |
| "Connection refused" | Ensure firewall allows outbound SMTP (port 587) |

---

## Settings.py Configuration

The following are now configured in `MainEnviroNode/settings.py`:

```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
FRONTEND_BASE_URL = os.getenv('FRONTEND_BASE_URL', 'http://127.0.0.1:8000')
```

**No hardcoded credentials.** All sensitive data via environment variables.

---

## Security Notes

✅ **Never commit credentials to git**
- Keep `.env` file in `.gitignore`
- Use environment variables only
- App passwords are safer than account passwords

✅ **Gmail App Passwords**
- Specific to Mail app on this computer
- Can be revoked anytime
- 16-character random string
- Different from account password

✅ **Email Links**
- Token expires after 7 days
- One-time use (invalidates after activation)
- Uses secure urlsafe encoding
- No credentials in email

---

## Files Changed

- `MainEnviroNode/settings.py` - Gmail SMTP config + FRONTEND_BASE_URL
- `AppEnviroNode/views.py` - Uses FRONTEND_BASE_URL for activation links
- `AppEnviroNode/services.py` - No changes (already correct)

---

## What Changed

| Before | After |
|--------|-------|
| Console backend (prints to terminal) | Gmail SMTP (real email) |
| `request.build_absolute_uri()` | `settings.FRONTEND_BASE_URL` |
| Hardcoded 127.0.0.1 in some cases | Dynamic based on env var |
| No credential management | Environment variables only |

---

## Production Deployment

When deploying to production:

1. **Enable 2FA & Generate App Password** (same as above)
2. **Set environment variables** on production server:
   ```bash
   export EMAIL_HOST_USER="admin@gmail.com"
   export EMAIL_HOST_PASSWORD="xxxx xxxx xxxx xxxx"
   export FRONTEND_BASE_URL="https://yourdomain.com"
   ```
3. **Test email** by inviting a user
4. **Monitor** email_debug.log for errors

For platforms like Render, Heroku, Railway:
- Set env vars in dashboard, not in code
- Ensure credentials are marked as "secret"

---

## Alternative Email Services

If not using Gmail, update EMAIL_BACKEND:

**SendGrid:**
```python
EMAIL_BACKEND = 'sendgrid_backend.SendgridBackend'
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
```

**AWS SES, Mailgun, Postmark:** Similar approach with their SDKs

---

**Status: ✅ Ready for Gmail SMTP**

All activation links are now dynamic and email will send to real Gmail accounts.
