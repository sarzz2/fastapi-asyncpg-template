import base64
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any

import pyotp
import segno
from cryptography.fernet import Fernet

from api.core.config import settings


def _get_fernet(key: str) -> Fernet:
    """
    Derive a Fernet instance from the provided key.
    Accepts valid base64 Fernet keys or derives a key via SHA-256.

    Args:
        key (str): The key to derive the Fernet instance from

    Returns:
        Fernet: The Fernet instance
    """
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError):
        derived_key = base64.urlsafe_b64encode(hashlib.sha256(key.encode("utf-8")).digest())
        return Fernet(derived_key)


def encrypt_secret(secret: str, key: str | None = None) -> str:
    """
    Encrypt a TOTP secret using Fernet.

    Args:
        secret (str): The TOTP secret to encrypt
        key (str | None): The encryption key (optional, uses default if not provided)

    Returns:
        str: The encrypted TOTP secret
    """
    encryption_key = key or settings.TWO_FACTOR_ENCRYPTION_KEY
    fernet = _get_fernet(encryption_key)
    return fernet.encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_secret(encrypted_secret: str, key: str | None = None) -> str:
    """
    Decrypt an encrypted TOTP secret using Fernet.

    Args:
        encrypted_secret (str): The encrypted TOTP secret to decrypt
        key (str | None): The decryption key (optional, uses default if not provided)

    Returns:
        str: The decrypted TOTP secret
    """
    encryption_key = key or settings.TWO_FACTOR_ENCRYPTION_KEY
    fernet = _get_fernet(encryption_key)
    return fernet.decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")


def generate_totp_secret() -> str:
    """
    Generate a new cryptographically random Base32 TOTP secret.

    Returns:
        str: A new TOTP secret
    """
    return pyotp.random_base32()


def generate_provisioning_uri(secret: str, name: str, issuer_name: str | None = None) -> str:
    """
    Generate an otpauth:// provisioning URI for authenticator applications.

    Args:
        secret (str): The TOTP secret
        name (str): The user's name
        issuer_name (str | None): The issuer name

    Returns:
        str: The provisioning URI
    """
    issuer = issuer_name or settings.TWO_FACTOR_ISSUER_NAME
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=name, issuer_name=issuer)


def generate_qr_code_svg(uri: str) -> str:
    """
    Generate an inline SVG Data URI for the provisioning URI.

    Args:
        uri (str): The provisioning URI

    Returns:
        str: The SVG Data URI
    """
    qr = segno.make(uri)
    return qr.svg_data_uri()


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    """
    Verify a 6-digit TOTP code against a secret with clock drift tolerance.

    Args:
        secret (str): The TOTP secret
        code (str): The OTP code
        valid_window (int): The number of valid time windows to check

    Returns:
        bool: True if the code is valid, False otherwise
    """
    cleaned_code = code.strip().replace(" ", "")
    if not cleaned_code.isdigit() or len(cleaned_code) != 6:
        return False
    totp = pyotp.TOTP(secret)
    return bool(totp.verify(cleaned_code, valid_window=valid_window))


def hash_backup_code(code: str) -> str:
    """
    Hash a single backup code using SHA-256.

    Args:
        code (str): The backup code to hash

    Returns:
        str: The hashed backup code
    """
    normalized = code.strip().replace("-", "").upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_backup_codes(count: int = 8) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Generate plaintext backup codes and their corresponding hash records for storage.
    Format: XXXX-XXXX (e.g. A1B2-C3D4)

    Args:
        count (int): The number of backup codes to generate

    Returns:
        tuple[list[str], list[dict[str, Any]]]: A tuple containing the plaintext backup codes and their hashed records
    """
    plaintext_codes: list[str] = []
    hashed_records: list[dict[str, Any]] = []

    for _ in range(count):
        part1 = secrets.token_hex(2).upper()
        part2 = secrets.token_hex(2).upper()
        code = f"{part1}-{part2}"
        plaintext_codes.append(code)
        hashed_records.append(
            {
                "code_hash": hash_backup_code(code),
                "used": False,
                "used_at": None,
            }
        )

    return plaintext_codes, hashed_records


def verify_and_consume_backup_code(
    backup_codes: list[dict[str, Any]], candidate_code: str
) -> tuple[bool, list[dict[str, Any]]]:
    """
    Verify candidate code against list of stored hashed backup codes.
    If valid and unused, marks it as used and returns True with updated list.

    Args:
        backup_codes (list[dict[str, Any]]): The list of hashed backup codes
        candidate_code (str): The candidate backup code

    Returns:
        tuple[bool, list[dict[str, Any]]]: Tuple of (is_valid, updated_backup_codes)
    """
    candidate_hash = hash_backup_code(candidate_code)
    updated_codes = [dict(c) for c in backup_codes]

    for item in updated_codes:
        if item.get("code_hash") == candidate_hash and not item.get("used", False):
            item["used"] = True
            item["used_at"] = datetime.now(timezone.utc).isoformat()
            return True, updated_codes

    return False, updated_codes
