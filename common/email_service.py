import os
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR.parent / ".env")
TEMPLATE_DIR = BASE_DIR / "email_templates"


class EmailConfigurationError(RuntimeError):
    """Raised when required email configuration is missing."""


def _render_template(template_name: str, context: Mapping[str, str] | None = None) -> str:
    template_path = TEMPLATE_DIR / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Email template '{template_name}' not found at {template_path}.")

    html = template_path.read_text(encoding="utf-8")
    if not context:
        return html

    rendered = html
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)

    return rendered


def send_templated_email(
    *,
    to_email: str,
    subject: str,
    template_name: str,
    context: Mapping[str, str] | None = None,
) -> tuple[int, str | None]:
    """Send an email via SendGrid and return (status_code, message_id)."""
    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("SENDGRID_FROM_EMAIL")

    if not api_key:
        raise EmailConfigurationError("SENDGRID_API_KEY is not configured in the environment.")

    if not from_email:
        raise EmailConfigurationError("SENDGRID_FROM_EMAIL is not configured in the environment.")

    html_content = _render_template(template_name, context)

    message = Mail(
        from_email=from_email,
        to_emails=to_email,
        subject=subject,
        html_content=html_content,
    )

    sg = SendGridAPIClient(api_key)
    response = sg.send(message)

    status_code = getattr(response, "status_code", None)
    message_id = None
    if hasattr(response, "headers"):
        message_id = response.headers.get("X-Message-Id")

    return status_code, message_id
