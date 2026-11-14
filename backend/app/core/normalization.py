from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

import phonenumbers
from phonenumbers import PhoneNumberFormat


_EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}$",
    re.IGNORECASE,
)
_PHONE_FORMATTING = re.compile(r"[\s().\-/\[\]\u2010-\u2015]+")
_PHONE_REGION = os.getenv("DEFAULT_PHONE_REGION", "IN").upper()


@dataclass(frozen=True)
class PhoneDetails:
    phone: str | None
    country_code: str | None
    region: str | None
    national_number: str | None


def _title_word(value: str) -> str:
    lowered = value.lower()
    return lowered[:1].upper() + lowered[1:]


def normalize_person_name(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Name must not be blank")
    if len(normalized) > 160:
        raise ValueError("Name must be 160 characters or fewer")

    segments = re.split(r"([ '\u2019-])", normalized)
    if any(
        not segment
        or (
            segment not in {" ", "'", "\u2019", "-"}
            and any(
                unicodedata.category(char)[0] not in {"L", "M"}
                and not (
                    char == "."
                    and index > 0
                    and unicodedata.category(segment[index - 1])[0] in {"L", "M"}
                )
                for index, char in enumerate(segment)
            )
        )
        for segment in segments
    ):
        raise ValueError("Name may contain letters, spaces, periods, hyphens, and apostrophes")
    return "".join(
        segment if segment in {" ", "'", "\u2019", "-"} else _title_word(segment)
        for segment in segments
    )


def normalize_email(value: str | None, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError("Enter a valid email address")
        return None
    normalized = value.strip().lower()
    if not normalized:
        if required:
            raise ValueError("Enter a valid email address")
        return None
    if len(normalized) > 320 or _EMAIL_PATTERN.fullmatch(normalized) is None:
        raise ValueError("Enter a valid email address")
    return normalized


def _normalize_national_number(value: str) -> str:
    candidate = _PHONE_FORMATTING.sub("", value.strip())
    if not candidate or not candidate.isascii() or not candidate.isdigit():
        raise ValueError("Enter a phone number using digits and common formatting symbols")
    return candidate


def _validated_phone(value: str, region: str) -> phonenumbers.PhoneNumber:
    try:
        parsed = phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Enter a valid phone number for the selected country") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Enter a valid phone number for the selected country")
    return parsed


def normalize_phone_fields(
    phone: str | None,
    country_code: str | None,
    region: str | None,
    national_number: str | None,
) -> PhoneDetails:
    structured = (country_code, region, national_number)
    if any(value is not None and value.strip() for value in structured):
        if not all(value is not None and value.strip() for value in structured):
            raise ValueError("Choose a country and enter a complete phone number")
        normalized_region = region.strip().upper()
        if len(normalized_region) != 2 or normalized_region not in phonenumbers.SUPPORTED_REGIONS:
            raise ValueError("Choose a supported country")
        normalized_country_code = country_code.strip()
        if not re.fullmatch(r"\+\d{1,3}", normalized_country_code):
            raise ValueError("Country calling code must start with +")
        expected_code = phonenumbers.country_code_for_region(normalized_region)
        if expected_code != int(normalized_country_code[1:]):
            raise ValueError("Country calling code does not match the selected country")
        digits = _normalize_national_number(national_number)
        parsed = _validated_phone(digits, normalized_region)
        if parsed.country_code != expected_code:
            raise ValueError("Phone number does not match the selected country")
    elif phone is not None and phone.strip():
        legacy_value = phone.strip()
        try:
            parsed = _validated_phone(legacy_value, None)
        except ValueError:
            if legacy_value.startswith("+"):
                raise
            digits = _normalize_national_number(legacy_value)
            parsed = _validated_phone(digits, _PHONE_REGION)
    else:
        return PhoneDetails(None, None, None, None)

    international = phonenumbers.format_number(parsed, PhoneNumberFormat.INTERNATIONAL)
    return PhoneDetails(
        phone=international,
        country_code=f"+{parsed.country_code}",
        region=phonenumbers.region_code_for_number(parsed) or None,
        national_number=str(parsed.national_number),
    )
