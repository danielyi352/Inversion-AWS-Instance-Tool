from __future__ import annotations

import configparser
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, NoCredentialsError
from PySide6.QtCore import QThread, Signal

__all__ = [
    "DeployRequest",
    "DeployResult",
    "profile_sso_region",
    "AwsWorker",
    "DeploymentWorker",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DeployRequest:
    """Parameters the user selects in the GUI before deployment."""

    profile: str
    region: str
    account_id: str
    repository: str
    instance_type: str
    key_pair: str
    security_group: str
    volume_size: int


@dataclass
class DeployResult:
    """Subset of instance details surfaced back to the GUI."""

    instance_id: str
    public_dns: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def profile_sso_region(profile: str) -> str | None:
    """Return the SSO region configured for *profile* in ~/.aws/config."""

    cfg = configparser.ConfigParser()
    aws_config = Path.home() / ".aws" / "config"
    if not aws_config.exists():
        return None
    cfg.read(aws_config)
    section = "profile " + profile if profile != "default" else "default"
    return cfg.get(section, "sso_region", fallback=None)


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------


class AwsWorker(QThread):
    """Fetches ECR, key-pair and security-group lists without blocking the UI."""

    data_ready = Signal(dict)
    error = Signal(str)

    def __init__(self, profile: str, region: str) -> None:
        super().__init__()
        self._profile = profile
        self._region = region

    # pylint: disable-next=missing-function-docstring
    def run(self) -> None:  # noqa: D401
        try:
            session = boto3.Session(
                profile_name=self._profile, region_name=self._region
            )
            ecr = session.client("ecr")
            ec2 = session.client("ec2")

            repos = [
                r["repositoryName"]
                for r in ecr.describe_repositories().get("repositories", [])
            ]
            key_pairs = [
                k["KeyName"] for k in ec2.describe_key_pairs().get("KeyPairs", [])
            ]
            security_groups = [
                s["GroupName"]
                for s in ec2.describe_security_groups().get("SecurityGroups", [])
            ]

            self.data_ready.emit(
                {
                    "repositories": repos,
                    "key_pairs": key_pairs,
                    "security_groups": security_groups,
                }
            )
        except (BotoCoreError, NoCredentialsError) as exc:  # pragma: no cover
            self.error.emit(str(exc))


class DeploymentWorker(QThread):
    """Runs the deploy-ec2.sh script and streams logs / progress back to the GUI."""

    success = Signal(object)
    error = Signal(str)
    progress = Signal(int)
    log = Signal(str)

    _MILESTONES = (
        ("Checking AWS CLI prerequisites", 5),
        ("Key pair", 10),
        ("Finding latest", 15),
        ("Creating security group", 20),
        ("Launching EC2", 30),
        ("Waiting for instance state", 40),
        ("Waiting for AWS status checks", 50),
        ("SSH connection established", 55),
        ("Installing Docker", 60),
        ("Docker installation completed", 70),
        ("Configuring AWS credentials", 75),
        ("AWS SSO credentials configured", 80),
        ("Pulling", 85),
        ("Container deployment completed", 95),
        ("Deployment completed successfully", 100),
    )

    def __init__(self, req: DeployRequest):
        super().__init__()
        self._req = req

    # pylint: disable-next=too-many-branches
    def run(self) -> None:  # noqa: D401
        env = os.environ.copy() | {
            "AWS_REGION": self._req.region,
            "AWS_ACCOUNT_ID": self._req.account_id,
            "ECR_REPOSITORY": self._req.repository,
            "INSTANCE_TYPE": self._req.instance_type,
            "KEY_PAIR_NAME": self._req.key_pair,
            "SECURITY_GROUP_NAME": self._req.security_group,
            "VOLUME_SIZE": str(self._req.volume_size),
            "AWS_PROFILE": self._req.profile,
            "SSO_SESSION": self._req.profile,
        }

        base = Path(getattr(sys, "_MEIPASS", Path.cwd()))
        script_path = base / "deploy-ec2.sh"
        if not script_path.exists():
            script_path = Path(__file__).resolve().parent / "deploy-ec2.sh"
        if not script_path.exists():
            self.error.emit("deploy-ec2.sh not found in working directory.")
            return

        process = subprocess.Popen(
            ["bash", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )

        instance_id = public_dns = None

        assert process.stdout is not None  # for mypy
        for line in process.stdout:
            self.log.emit(line.rstrip())
            self._maybe_emit_progress(line)
            if "Instance launched:" in line:
                instance_id = line.strip().split()[-1]
            elif "Public DNS:" in line:
                public_dns = line.strip().split()[-1]

        process.wait()
        if process.returncode != 0:
            if instance_id:
                subprocess.call(
                    [
                        "aws",
                        "ec2",
                        "terminate-instances",
                        "--instance-ids",
                        instance_id,
                        "--region",
                        self._req.region,
                        "--profile",
                        self._req.profile,
                    ]
                )
            self.error.emit("Deployment script failed. See log for details.")
            return

        if not all((instance_id, public_dns)):
            self.error.emit("Deployment finished but could not parse instance details.")
            return

        self.progress.emit(100)
        self.success.emit(DeployResult(instance_id, public_dns))

    def _maybe_emit_progress(self, line: str):
        lowered = line.lower()
        for text, pct in self._MILESTONES:
            if text.lower() in lowered:
                self.progress.emit(pct)
                break
