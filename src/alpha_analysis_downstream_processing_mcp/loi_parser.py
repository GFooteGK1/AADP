"""LOI PDF address extraction and verification."""

from __future__ import annotations

import logging
import re

import pymupdf

logger = logging.getLogger("[loi_parser]")

# Matches the address in the Premises field of an Alpha LOI.
# Pattern: "within <ADDRESS, CITY, ST ZIP>" before ", shown"
_PREMISES_ADDRESS_RE = re.compile(
    r"within\s+(.+?\d{5})",
    re.IGNORECASE,
)

# Strip "New Site - " or "New Site: " prefix from email subjects
_SUBJECT_PREFIX_RE = re.compile(r"^New\s+Site\s*[-:]\s*", re.IGNORECASE)


def extract_address_from_loi_pdf(pdf_bytes: bytes) -> str | None:
    """Extract the premises address from an LOI PDF.

    Looks for the address in the Premises section on page 1,
    which follows the pattern: "within {address}, shown".

    Args:
        pdf_bytes: Raw PDF file content.

    Returns:
        The extracted address string, or None if not found.
    """
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        logger.exception("Failed to open PDF")
        return None

    if len(doc) == 0:
        logger.warning("PDF has no pages")
        return None

    text = doc[0].get_text()
    doc.close()

    match = _PREMISES_ADDRESS_RE.search(text)
    if not match:
        logger.warning("Could not find premises address in LOI PDF text")
        logger.debug("Page 1 text: %s", text[:500])
        return None

    address = match.group(1).strip().rstrip(",")
    logger.info("Extracted LOI premises address: %s", address)
    return address


def extract_address_from_subject(subject: str) -> str | None:
    """Extract the address portion from an email subject line.

    Strips the "New Site - " or "New Site: " prefix.

    Args:
        subject: Email subject line.

    Returns:
        The address string, or None if the subject doesn't match.
    """
    result = _SUBJECT_PREFIX_RE.sub("", subject).strip()
    if not result or result == subject.strip():
        logger.warning("Could not extract address from subject: %s", subject)
        return None
    logger.info("Extracted subject address: %s", result)
    return result


def verify_loi_address(
    subject_address: str | None,
    loi_address: str | None,
) -> dict[str, str | bool | None]:
    """Compare subject and LOI addresses, preferring the LOI address.

    Args:
        subject_address: Address extracted from email subject.
        loi_address: Address extracted from LOI PDF.

    Returns:
        Dict with verified_address, source, and mismatch flag.
    """
    if loi_address and subject_address:
        # Normalize for comparison: lowercase, collapse whitespace
        norm_loi = " ".join(loi_address.lower().split())
        norm_subj = " ".join(subject_address.lower().split())
        mismatch = norm_subj not in norm_loi and norm_loi not in norm_subj
        if mismatch:
            logger.warning(
                "Address mismatch — subject: %r vs LOI: %r. Using LOI address.",
                subject_address,
                loi_address,
            )
        return {
            "verified_address": loi_address,
            "source": "loi",
            "mismatch": mismatch,
            "subject_address": subject_address,
            "loi_address": loi_address,
        }

    if loi_address:
        return {
            "verified_address": loi_address,
            "source": "loi",
            "mismatch": False,
            "subject_address": subject_address,
            "loi_address": loi_address,
        }

    if subject_address:
        logger.warning("No LOI address found, falling back to subject address")
        return {
            "verified_address": subject_address,
            "source": "subject",
            "mismatch": False,
            "subject_address": subject_address,
            "loi_address": None,
        }

    return {
        "verified_address": None,
        "source": None,
        "mismatch": False,
        "subject_address": None,
        "loi_address": None,
    }
