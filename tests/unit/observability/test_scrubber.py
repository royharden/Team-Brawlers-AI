"""PHI scrubber unit tests — master plan §12.

Each PHI category has positive (must redact) and negative (must NOT touch)
cases, plus a nested-dict case proving recursion works through containers.
"""

from __future__ import annotations

import pytest

from agentforge.observability.scrubber import scrub_phi, scrub_phi_in_obj

# --- SSN ----------------------------------------------------------------------


@pytest.mark.unit
def test_scrub_ssn_positive() -> None:
    out = scrub_phi("Patient SSN is 123-45-6789, please verify.")
    assert "123-45-6789" not in out
    assert "[REDACTED-SSN]" in out


@pytest.mark.unit
def test_scrub_ssn_negative_not_a_match() -> None:
    # Plain non-SSN text untouched.
    text = "The room number is 12-345 and lab code A45."
    assert scrub_phi(text) == text


# --- Phone --------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone",
    [
        "555-867-5309",
        "(555) 867-5309",
        "555.867.5309",
        "+1 555 867 5309",
        "5558675309",
    ],
)
def test_scrub_phone_positive(phone: str) -> None:
    out = scrub_phi(f"Call me at {phone} tomorrow.")
    assert phone not in out
    assert "[REDACTED-PHONE]" in out


@pytest.mark.unit
def test_scrub_phone_negative_short_number() -> None:
    text = "Code is 4321."
    assert scrub_phi(text) == text


# --- Email --------------------------------------------------------------------


@pytest.mark.unit
def test_scrub_email_positive() -> None:
    out = scrub_phi("Contact: jane.doe+test@example.com for results.")
    assert "jane.doe+test@example.com" not in out
    assert "[REDACTED-EMAIL]" in out


@pytest.mark.unit
def test_scrub_email_negative_not_email() -> None:
    text = "Use the @here mention or #channel reference."
    assert scrub_phi(text) == text


# --- DOB ----------------------------------------------------------------------


@pytest.mark.unit
def test_scrub_dob_iso_positive() -> None:
    out = scrub_phi("DOB: 1985-07-22.")
    assert "1985-07-22" not in out
    assert "[REDACTED-DOB]" in out


@pytest.mark.unit
def test_scrub_dob_us_positive() -> None:
    out = scrub_phi("Born 07/22/1985.")
    assert "07/22/1985" not in out
    assert "[REDACTED-DOB]" in out


@pytest.mark.unit
def test_scrub_dob_negative_invalid_date() -> None:
    # Month 13 is not a valid DOB shape and should NOT be redacted as DOB.
    text = "Invoice 13/45/2024 ref."
    out = scrub_phi(text)
    assert "[REDACTED-DOB]" not in out


# --- MRN ----------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "mrn",
    ["MRN-123456", "MRN: 87654", "mrn-44455", "MR123456"],
)
def test_scrub_mrn_positive(mrn: str) -> None:
    out = scrub_phi(f"Lookup {mrn} in chart.")
    assert mrn not in out
    assert "[REDACTED-MRN]" in out


@pytest.mark.unit
def test_scrub_mrn_negative_not_mrn() -> None:
    text = "Mr. Smith arrived at the front desk."
    assert scrub_phi(text) == text


# --- Credit card --------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "cc",
    [
        "4111 1111 1111 1111",
        "4111-1111-1111-1111",
        "4111111111111111",
        "378282246310005",  # 15-digit Amex
    ],
)
def test_scrub_cc_positive(cc: str) -> None:
    out = scrub_phi(f"Card: {cc} expires soon.")
    assert cc not in out
    assert "[REDACTED-CC]" in out


@pytest.mark.unit
def test_scrub_cc_negative_short_runs() -> None:
    text = "Ref 12345 group A."
    out = scrub_phi(text)
    assert "[REDACTED-CC]" not in out


# --- Generic long-digit (9-11) ------------------------------------------------


@pytest.mark.unit
def test_scrub_long_digits_preserves_last4() -> None:
    out = scrub_phi("Account 123456789")  # 9-digit number
    assert "123456789" not in out
    assert "****-6789" in out


@pytest.mark.unit
def test_scrub_long_digits_negative_short() -> None:
    text = "Bay 1234."
    assert scrub_phi(text) == text


# --- Recursion through dict / list --------------------------------------------


@pytest.mark.unit
def test_scrub_in_dict_nested() -> None:
    obj = {
        "patient": {
            "ssn": "123-45-6789",
            "contact": {
                "email": "a@b.com",
                "phone": "555-867-5309",
            },
            "notes": ["DOB: 1985-07-22", "MRN-9999 chart pulled"],
        },
        "count": 3,  # unchanged
        "active": True,  # unchanged
    }
    out = scrub_phi_in_obj(obj)
    assert out["count"] == 3
    assert out["active"] is True
    assert "[REDACTED-SSN]" in out["patient"]["ssn"]
    assert "[REDACTED-EMAIL]" in out["patient"]["contact"]["email"]
    assert "[REDACTED-PHONE]" in out["patient"]["contact"]["phone"]
    assert any("[REDACTED-DOB]" in s for s in out["patient"]["notes"])
    assert any("[REDACTED-MRN]" in s for s in out["patient"]["notes"])


@pytest.mark.unit
def test_scrub_in_list_of_strings() -> None:
    obj = ["SSN 123-45-6789", "email a@b.com", "no PHI here"]
    out = scrub_phi_in_obj(obj)
    assert "[REDACTED-SSN]" in out[0]
    assert "[REDACTED-EMAIL]" in out[1]
    assert out[2] == "no PHI here"


@pytest.mark.unit
def test_scrub_in_obj_passes_through_non_containers() -> None:
    assert scrub_phi_in_obj(42) == 42
    assert scrub_phi_in_obj(3.14) == 3.14
    assert scrub_phi_in_obj(None) is None
    assert scrub_phi_in_obj(True) is True
    assert scrub_phi_in_obj(b"raw") == b"raw"


@pytest.mark.unit
def test_scrub_empty_string_unchanged() -> None:
    assert scrub_phi("") == ""
