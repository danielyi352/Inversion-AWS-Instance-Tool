"""
FastAPI bridge that exposes the existing deployer engine over HTTP so the new
web UI can call into the same AWS workflows (SSO/login, metadata fetch, deploy,
terminate, connect).
"""

from __future__ import annotations

import os
import subprocess
import sys
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ------------------------------------------------------------------------------
# FastAPI setup
# ------------------------------------------------------------------------------

app = FastAPI(title="Inversion Deployer API", version="1.0.0")

# Allow local dev server (Vite) to talk to the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------------------


class LoginRequest(BaseModel):
    profile: str = Field(default="default")
    region: str = Field(default="us-east-1")


class DeployRequestModel(BaseModel):
    profile: str
    region: str
    account_id: str
    repository: str
    instance_type: str
    key_pair: str
    security_group: str
    volume_size: int = Field(default=30, ge=1, le=2048)


class TerminateRequest(BaseModel):
    profile: str
    region: str
    instance_id: str


class ConnectRequest(BaseModel):
    profile: str
    region: str
    instance_id: str
    ssh_user: str = Field(default="ubuntu")
    key_path: Optional[str] = None
    launch_terminal: bool = Field(default=True)


class UploadRequest(BaseModel):
    profile: str
    region: str
    instance_id: str
    local_path: str
    destination_path: str
    ssh_user: str = Field(default="ubuntu")
    key_path: Optional[str] = None


class DownloadRequest(BaseModel):
    profile: str
    region: str
    instance_id: str
    remote_path: str
    local_path: str
    ssh_user: str = Field(default="ubuntu")
    key_path: Optional[str] = None


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
AwsMilestones = (
    ("checking aws cli prerequisites", 5),
    ("key pair", 10),
    ("finding latest", 15),
    ("creating security group", 20),
    ("launching ec2", 30),
    ("waiting for instance state", 40),
    ("waiting for aws status checks", 50),
    ("ssh connection established", 55),
    ("installing docker", 60),
    ("docker installation completed", 70),
    ("configuring aws credentials", 75),
    ("aws sso credentials configured", 80),
    ("pulling", 85),
    ("container deployment completed", 95),
    ("deployment completed successfully", 100),
)


def _session(profile: str, region: str):
    try:
        return boto3.Session(profile_name=profile, region_name=region)
    except (BotoCoreError, NoCredentialsError) as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _run(cmd: List[str], env: Optional[Dict[str, str]] = None) -> str:
    try:
        return subprocess.check_output(
            cmd, text=True, stderr=subprocess.STDOUT, env=env
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=exc.output) from exc


def _script_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path.cwd()))
    candidate = base / "deploy-ec2.sh"
    if candidate.exists():
        return candidate
    fallback = Path(__file__).resolve().parent / "deploy-ec2.sh"
    if fallback.exists():
        return fallback
    raise HTTPException(status_code=500, detail="deploy-ec2.sh not found.")


def _run_deploy_script(req: DeployRequestModel) -> Dict[str, Any]:
    env = os.environ.copy() | {
        "AWS_REGION": req.region,
        "AWS_ACCOUNT_ID": req.account_id,
        "ECR_REPOSITORY": req.repository,
        "INSTANCE_TYPE": req.instance_type,
        "KEY_PAIR_NAME": req.key_pair,
        "SECURITY_GROUP_NAME": req.security_group,
        "VOLUME_SIZE": str(req.volume_size),
        "AWS_PROFILE": req.profile,
        "SSO_SESSION": req.profile,
    }

    process = subprocess.Popen(
        ["bash", str(_script_path())],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    logs: List[str] = []
    instance_id = None
    public_dns = None

    assert process.stdout is not None  # for mypy
    for line in process.stdout:
        logs.append(line.rstrip())
        if "Instance launched:" in line:
            instance_id = line.strip().split()[-1]
        elif "Public DNS:" in line:
            public_dns = line.strip().split()[-1]

    process.wait()
    if process.returncode != 0:
        # Try to terminate the instance if we managed to capture an ID.
        if instance_id:
            try:
                _run(
                    [
                        "aws",
                        "ec2",
                        "terminate-instances",
                        "--instance-ids",
                        instance_id,
                        "--region",
                        req.region,
                        "--profile",
                        req.profile,
                    ]
                )
            except HTTPException:
                # If termination fails, still surface original error.
                pass
        raise HTTPException(
            status_code=500,
            detail="Deployment script failed. Check logs for details.",
        )

    if not (instance_id and public_dns):
        raise HTTPException(
            status_code=500,
            detail="Deployment finished but instance details were missing.",
        )

    return {
        "instance": {
            "id": instance_id,
            "publicDns": public_dns,
            "instanceType": req.instance_type,
        },
        "logs": logs,
    }


def _sse(event: str, data: Any) -> str:
    import json

    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _describe_instance_dns(profile: str, region: str, instance_id: str) -> str:
    session = _session(profile, region)
    ec2 = session.client("ec2")
    try:
        resp = ec2.describe_instances(InstanceIds=[instance_id])
    except (BotoCoreError, ClientError) as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    for reservation in resp.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            dns = inst.get("PublicDnsName", "")
            if dns:
                return dns
    raise HTTPException(status_code=404, detail="Instance public DNS not found")


# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------


@app.post("/api/sso/login")
def sso_login(body: LoginRequest):
    """Trigger AWS SSO login for the given profile/region."""
    output = _run(
        ["aws", "sso", "login", "--profile", body.profile, "--region", body.region]
    )
    return {"status": "ok", "message": output}


@app.get("/api/metadata")
def metadata(profile: str = "default", region: str = "us-east-1"):
    """Fetch repositories, key pairs, and security groups for the profile/region."""
    session = _session(profile, region)
    ecr = session.client("ecr")
    ec2 = session.client("ec2")

    try:
        repos = [
            r["repositoryName"]
            for r in ecr.describe_repositories().get("repositories", [])
        ]
        key_pairs = [k["KeyName"] for k in ec2.describe_key_pairs().get("KeyPairs", [])]
        security_groups = [
            s["GroupName"]
            for s in ec2.describe_security_groups().get("SecurityGroups", [])
        ]
    except (BotoCoreError, ClientError) as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "repositories": repos,
        "keyPairs": key_pairs,
        "securityGroups": security_groups,
    }


@app.get("/api/instances")
def instances(profile: str = "default", region: str = "us-east-1"):
    """List running EC2 instances for the profile/region."""
    session = _session(profile, region)
    ec2 = session.client("ec2")
    try:
        resp = ec2.describe_instances(
            Filters=[
                {
                    "Name": "instance-state-name",
                    "Values": ["pending", "running", "stopping", "stopped"],
                }
            ]
        )
    except (BotoCoreError, ClientError) as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    results = []
    for reservation in resp.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            name_tag = next(
                (
                    tag.get("Value")
                    for tag in inst.get("Tags", [])
                    if tag.get("Key") == "Name"
                ),
                "",
            )
            results.append(
                {
                    "id": inst.get("InstanceId"),
                    "name": name_tag or inst.get("InstanceId"),
                    "status": inst.get("State", {}).get("Name", "unknown"),
                    "publicDns": inst.get("PublicDnsName", ""),
                    "instanceType": inst.get("InstanceType", ""),
                    "launchTime": (
                        inst.get("LaunchTime").isoformat()
                        if inst.get("LaunchTime")
                        else ""
                    ),
                }
            )

    return {"instances": results}


@app.post("/api/deploy")
def deploy(body: DeployRequestModel):
    """Run the existing deploy-ec2.sh script with the provided parameters."""
    payload = _run_deploy_script(body)
    return {"status": "ok", **payload}


@app.get("/api/deploy/stream")
def deploy_stream(
    profile: str,
    region: str,
    account_id: str,
    repository: str,
    instance_type: str,
    key_pair: str,
    security_group: str,
    volume_size: int = 30,
):
    """Stream deploy logs as server-sent events while running deploy-ec2.sh."""

    req = DeployRequestModel(
        profile=profile,
        region=region,
        account_id=account_id,
        repository=repository,
        instance_type=instance_type,
        key_pair=key_pair,
        security_group=security_group,
        volume_size=volume_size,
    )

    def event_stream():
        env = os.environ.copy() | {
            "AWS_REGION": req.region,
            "AWS_ACCOUNT_ID": req.account_id,
            "ECR_REPOSITORY": req.repository,
            "INSTANCE_TYPE": req.instance_type,
            "KEY_PAIR_NAME": req.key_pair,
            "SECURITY_GROUP_NAME": req.security_group,
            "VOLUME_SIZE": str(req.volume_size),
            "AWS_PROFILE": req.profile,
            "SSO_SESSION": req.profile,
        }

        process = subprocess.Popen(
            ["bash", str(_script_path())],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )

        instance_id = None
        public_dns = None

        assert process.stdout is not None  # for mypy
        for line in process.stdout:
            line = line.rstrip()
            yield _sse("log", line)
            lower = line.lower()
            for text, pct in AwsMilestones:
                if text in lower:
                    yield _sse("progress", pct)
                    break
            if "Instance launched:" in line:
                instance_id = line.strip().split()[-1]
            elif "Public DNS:" in line:
                public_dns = line.strip().split()[-1]

        process.wait()
        if process.returncode != 0:
            if instance_id:
                try:
                    _run(
                        [
                            "aws",
                            "ec2",
                            "terminate-instances",
                            "--instance-ids",
                            instance_id,
                            "--region",
                            req.region,
                            "--profile",
                            req.profile,
                        ]
                    )
                except HTTPException:
                    pass
            yield _sse("error", "Deployment failed. Check logs.")
            return

        if not (instance_id and public_dns):
            yield _sse(
                "error", "Deployment finished but instance details were missing."
            )
            return

        yield _sse(
            "complete",
            {
                "instance": {
                    "id": instance_id,
                    "publicDns": public_dns,
                    "instanceType": req.instance_type,
                }
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/terminate")
def terminate(body: TerminateRequest):
    session = _session(body.profile, body.region)
    ec2 = session.client("ec2")
    try:
        ec2.terminate_instances(InstanceIds=[body.instance_id])
    except (BotoCoreError, ClientError) as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok"}


@app.post("/api/connect")
def connect(body: ConnectRequest):
    public_dns = _describe_instance_dns(body.profile, body.region, body.instance_id)
    key_path = os.path.expanduser(body.key_path or f"~/.ssh/{body.instance_id}.pem")
    ssh_cmd = f"ssh -i {shlex.quote(key_path)} {body.ssh_user}@{public_dns}"

    launched = False
    launch_error = None
    if body.launch_terminal and sys.platform == "darwin":
        # Escape double quotes for AppleScript while keeping the raw command (no shell wrapping)
        escaped_cmd = ssh_cmd.replace('"', '\\"')
        osa = f'tell application "Terminal" to do script "{escaped_cmd}"'
        try:
            subprocess.check_call(["osascript", "-e", osa])
            launched = True
        except subprocess.CalledProcessError as exc:  # pragma: no cover
            launch_error = exc.output or str(exc)

    return {
        "status": "ok",
        "sshCommand": ssh_cmd,
        "publicDns": public_dns,
        "launched": launched,
        "launchError": launch_error,
    }


@app.post("/api/upload")
def upload(body: UploadRequest):
    dns = _describe_instance_dns(body.profile, body.region, body.instance_id)
    key_path = os.path.expanduser(body.key_path or "~/.ssh/id_rsa")
    local = os.path.expanduser(body.local_path)
    dest = f"{body.ssh_user}@{dns}:{body.destination_path}"
    try:
        subprocess.check_call(["scp", "-i", key_path, local, dest])
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=exc.output or str(exc)) from exc
    return {"status": "ok", "message": f"Uploaded {local} to {dest}"}


@app.post("/api/download")
def download(body: DownloadRequest):
    dns = _describe_instance_dns(body.profile, body.region, body.instance_id)
    key_path = os.path.expanduser(body.key_path or "~/.ssh/id_rsa")
    local = os.path.expanduser(body.local_path or ".")
    remote = f"{body.ssh_user}@{dns}:{body.remote_path}"
    try:
        subprocess.check_call(["scp", "-i", key_path, remote, local])
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=exc.output or str(exc)) from exc
    return {"status": "ok", "message": f"Downloaded {remote} to {local}"}
