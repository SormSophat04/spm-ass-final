import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
import requests

from config import Config


class EmailDeliveryError(Exception):
    """Raised when sending an email fails or email transport is not configured."""

    def __init__(self, message: str, code: str = "delivery_failed"):
        super().__init__(message)
        self.message = message
        self.code = code


def _env_str(key: str, default: str = "") -> str:
    return (os.getenv(key, default) or "").strip()


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def get_email_delivery_status() -> dict:
    """Inspect environment variables to determine active real-email delivery provider."""
    provider_pref = _env_str("MAIL_PROVIDER", Config.MAIL_PROVIDER).lower() or "auto"

    resend_api_key = _env_str("RESEND_API_KEY", Config.RESEND_API_KEY)
    resend_from = _env_str("RESEND_FROM_EMAIL", Config.RESEND_FROM_EMAIL)

    smtp_host = _env_str("SMTP_HOST", Config.SMTP_HOST)
    smtp_port = _env_int("SMTP_PORT", Config.SMTP_PORT)
    smtp_username = _env_str("SMTP_USERNAME", Config.SMTP_USERNAME)
    smtp_password = _env_str("SMTP_PASSWORD", Config.SMTP_PASSWORD)
    smtp_from = _env_str("SMTP_FROM_EMAIL", Config.SMTP_FROM_EMAIL) or smtp_username
    smtp_from_name = _env_str("SMTP_FROM_NAME", Config.SMTP_FROM_NAME) or "AcadCoord Institutional Portal"

    resend_ready = bool(resend_api_key and resend_from)
    smtp_ready = bool(smtp_host and smtp_from and (smtp_username == "" or smtp_password != ""))

    active_provider = None
    from_email = None

    if provider_pref == "resend":
        if resend_ready:
            active_provider = "resend"
            from_email = resend_from
    elif provider_pref == "smtp":
        if smtp_ready:
            active_provider = "smtp"
            from_email = smtp_from
    else:
        # auto: prefer SMTP when configured, otherwise Resend
        if smtp_ready:
            active_provider = "smtp"
            from_email = smtp_from
        elif resend_ready:
            active_provider = "resend"
            from_email = resend_from

    return {
        "configured": active_provider is not None,
        "provider": active_provider,
        "provider_preference": provider_pref,
        "from_email": from_email,
        "from_name": smtp_from_name,
        "smtp_host": smtp_host if active_provider == "smtp" else None,
        "smtp_port": smtp_port if active_provider == "smtp" else None,
        "expiry_minutes": _env_int("OTP_EXPIRY_MINUTES", Config.OTP_EXPIRY_MINUTES),
        "resend_cooldown_seconds": _env_int("OTP_RESEND_COOLDOWN_SECONDS", Config.OTP_RESEND_COOLDOWN_SECONDS),
        "otp_length": _env_int("OTP_LENGTH", Config.OTP_LENGTH),
    }


def _build_otp_email_content(
    recipient_email: str,
    otp_code: str,
    expiry_minutes: int,
    user_name: str | None = None,
) -> tuple[str, str, str]:
    greeting_name = escape(user_name) if user_name else escape(recipient_email.split("@")[0])
    spaced_code = " ".join(list(otp_code))
    subject = f"{otp_code} is your AcadCoord verification code"

    text_body = (
        f"Hello {user_name or recipient_email.split('@')[0]},\n\n"
        f"Your one-time verification code for AcadCoord Institutional Portal is:\n\n"
        f"    {otp_code}\n\n"
        f"This code expires in {expiry_minutes} minutes and can only be used once.\n"
        f"If you did not request this sign-in code, you can safely ignore this email.\n\n"
        f"-- AcadCoord Institutional Portal\n"
    )

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AcadCoord Verification Code</title>
</head>
<body style="margin:0;padding:24px;background-color:#EEF2F6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0F172A;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:520px;margin:0 auto;background:#FFFFFF;border:3px solid #0F172A;border-radius:12px;overflow:hidden;">
    <tr>
      <td style="background:#2563EB;padding:20px 24px;border-bottom:3px solid #0F172A;">
        <div style="font-size:18px;font-weight:900;color:#FFFFFF;letter-spacing:-0.02em;">
          AcadCoord // Institutional Portal
        </div>
        <div style="font-size:12px;font-weight:700;color:#DBEAFE;margin-top:4px;letter-spacing:0.04em;text-transform:uppercase;">
          One-Time Email Verification
        </div>
      </td>
    </tr>
    <tr>
      <td style="padding:26px 24px;">
        <p style="margin:0 0 12px;font-size:15px;font-weight:700;color:#0F172A;">
          Hello {greeting_name},
        </p>
        <p style="margin:0 0 20px;font-size:14px;line-height:1.55;color:#334155;">
          Use the 6-digit verification code below to finish signing in to your AcadCoord workspace.
        </p>
        <div style="background:#EFF6FF;border:2.5px solid #0F172A;border-radius:10px;padding:18px 16px;text-align:center;margin:0 0 20px;">
          <div style="font-family:'Courier New',Courier,monospace;font-size:32px;font-weight:900;letter-spacing:6px;color:#1D4ED8;">
            {escape(spaced_code)}
          </div>
          <div style="font-size:12px;font-weight:700;color:#475569;margin-top:8px;">
            Valid for {expiry_minutes} minutes · Single use only
          </div>
        </div>
        <p style="margin:0;font-size:12px;line-height:1.5;color:#64748B;">
          Never share this code with anyone. If you did not request to sign in with
          <strong>{escape(recipient_email)}</strong>, you can safely ignore this message.
        </p>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return subject, text_body, html_body


def _send_via_smtp(
    recipient_email: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    smtp_host = _env_str("SMTP_HOST", Config.SMTP_HOST)
    smtp_port = _env_int("SMTP_PORT", Config.SMTP_PORT)
    smtp_username = _env_str("SMTP_USERNAME", Config.SMTP_USERNAME)
    smtp_password = _env_str("SMTP_PASSWORD", Config.SMTP_PASSWORD)
    smtp_use_tls = _env_bool("SMTP_USE_TLS", Config.SMTP_USE_TLS)
    smtp_use_ssl = _env_bool("SMTP_USE_SSL", Config.SMTP_USE_SSL)
    from_email = _env_str("SMTP_FROM_EMAIL", Config.SMTP_FROM_EMAIL) or smtp_username
    from_name = _env_str("SMTP_FROM_NAME", Config.SMTP_FROM_NAME) or "AcadCoord Institutional Portal"

    # Gmail App Passwords are often copied with spaces ("abcd efgh ijkl mnop")
    if smtp_host.lower() == "smtp.gmail.com" and smtp_password:
        smtp_password = smtp_password.replace(" ", "")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = recipient_email
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    try:
        if smtp_use_ssl or smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15, context=context) as server:
                if smtp_username:
                    server.login(smtp_username, smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
                if smtp_use_tls:
                    server.starttls(context=context)
                    server.ehlo()
                if smtp_username:
                    server.login(smtp_username, smtp_password)
                server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        hint = (
            " For Gmail, make sure 2-Step Verification is enabled and use a 16-character Google App Password."
            if "gmail" in smtp_host.lower()
            else ""
        )
        raise EmailDeliveryError(
            f"SMTP authentication failed for '{smtp_username}'. Check SMTP_USERNAME and SMTP_PASSWORD in backend/.env.{hint}",
            code="smtp_auth_failed",
        ) from exc
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        raise EmailDeliveryError(
            f"Unable to deliver verification email via SMTP ({smtp_host}:{smtp_port}): {exc}",
            code="smtp_connection_failed",
        ) from exc


def _send_via_resend(
    recipient_email: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    api_key = _env_str("RESEND_API_KEY", Config.RESEND_API_KEY)
    from_email = _env_str("RESEND_FROM_EMAIL", Config.RESEND_FROM_EMAIL)
    from_name = _env_str("SMTP_FROM_NAME", Config.SMTP_FROM_NAME) or "AcadCoord Institutional Portal"
    sender = from_email if "<" in from_email else f"{from_name} <{from_email}>"

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": sender,
                "to": [recipient_email],
                "subject": subject,
                "text": text_body,
                "html": html_body,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise EmailDeliveryError(
            f"Unable to reach Resend API to send verification email: {exc}",
            code="resend_connection_failed",
        ) from exc

    if resp.status_code >= 400:
        detail = ""
        try:
            err_json = resp.json()
            detail = err_json.get("message") or err_json.get("error") or ""
        except Exception:
            detail = resp.text[:200]
        raise EmailDeliveryError(
            f"Resend API rejected the email ({resp.status_code}): {detail or 'Check RESEND_API_KEY and RESEND_FROM_EMAIL.'}",
            code="resend_api_error",
        )


def send_otp_email(
    recipient_email: str,
    otp_code: str,
    expiry_minutes: int | None = None,
    user_name: str | None = None,
) -> dict:
    """Send a real OTP verification email using the configured SMTP or Resend transport."""
    status = get_email_delivery_status()
    if not status["configured"]:
        raise EmailDeliveryError(
            "Real email delivery is not configured yet. Create backend/.env with SMTP credentials "
            "(SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD) or Resend credentials "
            "(RESEND_API_KEY, RESEND_FROM_EMAIL), then restart the backend.",
            code="email_not_configured",
        )

    ttl_mins = expiry_minutes or status["expiry_minutes"]
    subject, text_body, html_body = _build_otp_email_content(
        recipient_email=recipient_email,
        otp_code=otp_code,
        expiry_minutes=ttl_mins,
        user_name=user_name,
    )

    provider = status["provider"]
    if provider == "smtp":
        _send_via_smtp(recipient_email, subject, text_body, html_body)
    elif provider == "resend":
        _send_via_resend(recipient_email, subject, text_body, html_body)
    else:
        raise EmailDeliveryError(
            f"Unsupported email provider '{provider}'.",
            code="invalid_provider",
        )

    return {
        "provider": provider,
        "from_email": status["from_email"],
    }
