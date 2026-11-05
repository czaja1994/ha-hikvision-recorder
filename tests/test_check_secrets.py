"""Fail-closed behaviour of scripts/check_secrets.py (no network)."""
import subprocess
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


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


def test_history_scan_clean_repo(repo):
    (repo / "a.txt").write_text("nothing to see\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")
    assert check_secrets.scan_history(repo, {"S3CRET-VALUE"}) == []


def test_history_scan_finds_deleted_blob_message_and_other_branch(repo):
    secret = "S3CRET-VALUE"
    (repo / "keep.txt").write_text("fine\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")

    # Leaked in a file, removed again in the next commit.
    (repo / "leak.txt").write_text(f"line one\npassword = {secret.lower()}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add config")
    (repo / "leak.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "remove config")

    # Leaked only in a commit message.
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"debug with {secret}")

    # Leaked on a branch that is not checked out.
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "side.txt").write_text(f"x\n{secret}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "side work")
    _git(repo, "checkout", "-q", "main")

    found = check_secrets.scan_history(repo, {secret})
    joined = "\n".join(found)
    assert any(f.startswith("leak.txt:2 ") for f in found)
    assert any(f.startswith("side.txt:2 ") for f in found)
    assert sum(f.startswith("commit ") and "message" in f for f in found) == 1
    # Locations only, never the value.
    assert secret.lower() not in joined.lower()
    assert "keep.txt" not in joined


def test_history_scan_does_not_print_secret_in_path(repo):
    secret = "S3CRET-VALUE"
    (repo / f"{secret}.txt").write_text(f"{secret}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "oops")
    found = check_secrets.scan_history(repo, {secret})
    assert found
    assert secret.lower() not in "\n".join(found).lower()
