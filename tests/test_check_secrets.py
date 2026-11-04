"""Fail-closed behaviour of scripts/check_secrets.py (no network)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_secrets  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures"


def test_parses_serial_and_mac():
    text = (FIXTURE / "device_info.xml").read_text()
    assert check_secrets.parse_identifiers(text) == {
        "TESTSERIAL0001",
        "00:00:00:00:00:01",
    }


@pytest.mark.parametrize("name", ["busy.xml", "channels.xml"])
def test_wrong_shape_fails_closed(name):
    with pytest.raises(check_secrets.SecretCheckError):
        check_secrets.parse_identifiers((FIXTURE / name).read_text())


def test_empty_value_fails_closed():
    with pytest.raises(check_secrets.SecretCheckError):
        check_secrets.parse_identifiers(
            "<serialNumber> </serialNumber><macAddress>aa</macAddress>"
        )
