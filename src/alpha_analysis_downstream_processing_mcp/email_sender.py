"""AWS SES Email Sender for LOI notifications."""

import logging
import os
from dataclasses import dataclass, field
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Protocol

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("[email_sender]")

AWS_REGION = "us-east-1"  # Default AWS region for SES

# LOI email recipients
LOI_TO_ADDRESSES: list[str] = [
    "mswannie@cdsdevelopment.com",
    "DHowse@cdsdevelopment.com",
    "edu.ops@trilogy.com",
]
LOI_CC_ADDRESSES: list[str] = [
    "sahil.marwaha@trilogy.com",
    "greg.foote@trilogy.com",
    "andrew.vincent@trilogy.com",
    "aleks.rushing@huschblackwell.com",
]


class _SESClient(Protocol):
    def send_raw_email(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass
class EmailAttachment:
    """Email attachment configuration."""

    filename: str
    content: bytes
    content_type: str = "application/pdf"


@dataclass
class EmailConfig:
    """Email configuration."""

    to_addresses: list[str]
    cc_addresses: list[str] = field(default_factory=list)
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    attachments: list[EmailAttachment] = field(default_factory=list)


@dataclass
class LOIEmailData:
    """Data for LOI notification email."""

    full_address: str
    school_type: str  # "micro", "250", or "1000"
    sir_report_pdf: bytes | None = None
    sir_report_filename: str = "SIR_Report.pdf"

    # Derived fields
    grades_served: str = ""
    total_students: int = 0
    total_staff: str = ""
    architect: str = ""

    def __post_init__(self) -> None:
        """Set derived fields based on school_type."""
        normalized_school_type = self.school_type.strip().lower()
        self.school_type = normalized_school_type

        logger.info(
            "Deriving LOI email fields for school_type=%s", normalized_school_type
        )

        if normalized_school_type == "micro":
            self.grades_served = "K-8"
            self.total_students = 25
            self.total_staff = "4"
            self.architect = "Apogee"
        elif normalized_school_type == "250":
            self.grades_served = "K-12"
            self.total_students = 250
            self.total_staff = "TBD"
            self.architect = "David Bench"
        elif normalized_school_type == "1000":
            self.grades_served = "K-12"
            self.total_students = 1000
            self.total_staff = "TBD"
            self.architect = "David Bench"
        else:
            logger.warning(
                "Unknown school_type=%s while deriving LOI email fields",
                normalized_school_type,
            )


class SESEmailError(RuntimeError):
    """Error from SES email operations."""

    pass


def _get_ses_client() -> _SESClient:
    """Get AWS SES client."""
    # Use default credentials from environment or IAM role
    return boto3.client("ses", region_name=AWS_REGION)


def _get_sender_email() -> str:
    """Get the sender email address from environment."""
    sender = os.getenv("SES_SENDER_EMAIL")
    if not sender:
        raise SESEmailError(
            "SES_SENDER_EMAIL not found in environment. "
            "Please add it to your .env file."
        )
    return sender


def _get_loi_recipients() -> tuple[list[str], list[str]]:
    """
    Get LOI email recipients.

    Returns:
        Tuple of (to_addresses, cc_addresses)
    """
    return LOI_TO_ADDRESSES, LOI_CC_ADDRESSES


def send_email(config: EmailConfig) -> dict:
    """
    Send an email using AWS SES with attachments.

    Args:
        config: EmailConfig with all email settings

    Returns:
        Dict with 'message_id' and 'success' on success

    Raises:
        SESEmailError: If sending fails
    """
    if not config.to_addresses:
        raise SESEmailError("At least one recipient email address is required")

    sender = _get_sender_email()
    client = _get_ses_client()

    msg = MIMEMultipart("mixed")
    msg["Subject"] = config.subject
    msg["From"] = sender
    msg["To"] = ", ".join(config.to_addresses)
    if config.cc_addresses:
        msg["Cc"] = ", ".join(config.cc_addresses)

    # Create the body part
    body_part = MIMEMultipart("alternative")

    if config.body_text:
        text_part = MIMEText(config.body_text, "plain", "utf-8")
        body_part.attach(text_part)

    if config.body_html:
        html_part = MIMEText(config.body_html, "html", "utf-8")
        body_part.attach(html_part)

    msg.attach(body_part)

    # Add attachments
    for attachment in config.attachments:
        att = MIMEApplication(attachment.content)
        att.add_header(
            "Content-Disposition",
            "attachment",
            filename=attachment.filename,
        )
        att.add_header("Content-Type", attachment.content_type)
        msg.attach(att)

    # Build destination list
    all_recipients = list(config.to_addresses)
    all_recipients.extend(config.cc_addresses)

    try:
        response = client.send_raw_email(
            Source=sender,
            Destinations=all_recipients,
            RawMessage={"Data": msg.as_string()},
        )
        message_id = response.get("MessageId", "")
        logger.info("Email sent successfully: %s", message_id)
        return {"message_id": message_id, "success": True}

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        logger.error("SES send_raw_email failed: %s - %s", error_code, error_msg)
        raise SESEmailError(f"Failed to send email: {error_code} - {error_msg}") from e


def build_loi_email(
    data: LOIEmailData, extra_cc_addresses: list[str] | None = None
) -> EmailConfig:
    """
    Build the LOI notification email configuration.

    Args:
        data: LOIEmailData with address and SIR report
        extra_cc_addresses: Additional CC recipients (e.g. P1 Accountable emails)

    Returns:
        EmailConfig ready to be sent
    """
    to_addresses, cc_addresses = _get_loi_recipients()
    if extra_cc_addresses:
        # Deduplicate against existing recipients
        existing = {addr.lower() for addr in to_addresses + cc_addresses}
        for addr in extra_cc_addresses:
            if addr.lower() not in existing:
                cc_addresses.append(addr)
                existing.add(addr.lower())

    subject = f"New Site Kickoff: {data.full_address}"

    # Determine school type display name
    type_display = {
        "micro": "Micro",
        "250": "250",
        "1000": "1000",
    }.get(data.school_type, data.school_type.upper())

    # Build plain text body
    text_lines = [
        "I'm writing to kick off work on a new site. Here are the details:",
        "",
        "Site Information:",
        f"Full Address: {data.full_address}",
        f"Type of School: {type_display}",
        f"Architect: {data.architect}",
        f"Grades Served: {data.grades_served}",
        f"Total Students: {data.total_students}",
        f"Total Staff: {data.total_staff}",
        "",
        "Attachments:",
        f"- {data.sir_report_filename} (attached)",
        "",
        "Please review and let me know if you have any questions.",
    ]

    body_text = "\n".join(text_lines)

    # Build HTML body
    body_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        h2 {{
            color: #2c5282;
            border-bottom: 2px solid #2c5282;
            padding-bottom: 8px;
        }}
        .info-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0;
        }}
        .info-table td {{
            padding: 8px 12px;
            border-bottom: 1px solid #e2e8f0;
        }}
        .info-table td:first-child {{
            font-weight: 600;
            color: #4a5568;
            width: 40%;
        }}
        .attachments {{
            background: #ebf8ff;
            padding: 12px 16px;
            border-radius: 8px;
            border-left: 4px solid #3182ce;
            margin: 16px 0;
        }}
    </style>
</head>
<body>
    <p>I'm writing to kick off work on a new site. Here are the details:</p>

    <h2>Site Information</h2>
    <table class="info-table">
        <tr><td>Full Address</td><td>{data.full_address}</td></tr>
        <tr><td>Type of School</td><td>{type_display}</td></tr>
        <tr><td>Architect</td><td>{data.architect}</td></tr>
        <tr><td>Grades Served</td><td>{data.grades_served}</td></tr>
        <tr><td>Total Students</td><td>{data.total_students}</td></tr>
        <tr><td>Total Staff</td><td>{data.total_staff}</td></tr>
    </table>

    <div class="attachments">
        <strong>Attachments:</strong>
        <p style="margin: 4px 0;">📄 {data.sir_report_filename} (attached)</p>
    </div>

    <p style="margin-top: 24px;">Please review and let me know if you have any questions.</p>
</body>
</html>
"""

    # Build attachments list
    attachments: list[EmailAttachment] = []
    if data.sir_report_pdf:
        attachments.append(
            EmailAttachment(
                filename=data.sir_report_filename,
                content=data.sir_report_pdf,
                content_type="application/pdf",
            )
        )

    return EmailConfig(
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        attachments=attachments,
    )


def send_loi_email(
    data: LOIEmailData, extra_cc_addresses: list[str] | None = None
) -> dict:
    """
    Send the LOI notification email with SIR report attached.

    Args:
        data: LOIEmailData with address and SIR report
        extra_cc_addresses: Additional CC recipients (e.g. P1 Accountable emails)

    Returns:
        Dict with 'message_id' and 'success' on success

    Raises:
        SESEmailError: If sending fails
    """
    config = build_loi_email(data, extra_cc_addresses=extra_cc_addresses)
    logger.info(
        "Sending LOI email for %s to %s (cc: %s)",
        data.full_address,
        config.to_addresses,
        config.cc_addresses,
    )
    return send_email(config)
