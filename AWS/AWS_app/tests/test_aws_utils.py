import sys
from types import ModuleType
from unittest.mock import MagicMock
from pathlib import Path

# ---------------------------------------------------------------------------
# Stub external dependencies (PySide6, boto3, botocore) so tests can run in a
# lightweight environment without the full GUI / AWS SDK stack installed.
# ---------------------------------------------------------------------------
#   * Only minimal attributes used by aws_utils are provided.
#   * Stubs must be available BEFORE the module under test is imported.
# ---------------------------------------------------------------------------

# --- PySide6 stubs ----------------------------------------------------------
qt_core = ModuleType("PySide6.QtCore")

class _DummySignal:  # pylint: disable=too-few-public-methods
    def __init__(self, *_, **__):
        pass

    # Source code only calls .emit() / .connect(); provide no-op versions.
    def emit(self, *_, **__):
        pass

    def connect(self, *_, **__):
        pass

# Provide the minimal attributes accessed in aws_utils
qt_core.QThread = object  # Placeholder – functionality not needed in unit tests
qt_core.Signal = _DummySignal

sys.modules["PySide6"] = ModuleType("PySide6")
sys.modules["PySide6.QtCore"] = qt_core
sys.modules["PySide6.QtWidgets"] = ModuleType("PySide6.QtWidgets")  # unused but helps if imported later

# --- boto3 / botocore stubs -------------------------------------------------
sys.modules["boto3"] = MagicMock()
sys.modules["botocore"] = MagicMock()
sys.modules["botocore.exceptions"] = MagicMock()

# ---------------------------------------------------------------------------
# After stubbing, import the module under test
# ---------------------------------------------------------------------------
from aws_deployer_app.aws_utils import DeployRequest, DeployResult, profile_sso_region  # noqa: E402  pylint: disable=wrong-import-position


def test_profile_sso_region(tmp_path, monkeypatch):
    """profile_sso_region should return the configured SSO region for a profile
    and *None* when the profile or config file is missing."""

    # Create a temporary ~/.aws/config with a custom profile
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()
    config_file = aws_dir / "config"
    config_file.write_text("""[profile dev]\nsso_region = us-west-2\n""")

    # Monkey-patch Path.home() so that aws_utils looks in our temp directory
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert profile_sso_region("dev") == "us-west-2"
    # Unknown profile should fall back to *None*
    assert profile_sso_region("nonexistent") is None


def test_deploy_request_dataclass():
    """DeployRequest should store the provided values unchanged."""

    req = DeployRequest(
        profile="default",
        region="us-west-2",
        account_id="123456789012",
        repository="my-repo",
        instance_type="t3.micro",
        key_pair="test-key",
        security_group="sg-123",
        volume_size=50,
    )

    assert req.profile == "default"
    assert req.region == "us-west-2"
    assert req.volume_size == 50


def test_deploy_result_dataclass():
    """DeployResult should expose instance_id and public_dns attributes."""

    res = DeployResult(instance_id="i-abc", public_dns="ec2-example.amazonaws.com")
    assert res.instance_id == "i-abc"
    assert res.public_dns.startswith("ec2-") 