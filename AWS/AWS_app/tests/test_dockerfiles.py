import re
from pathlib import Path
import pytest

# Relative paths (from repository root) to the Dockerfiles we want to test
DOCKERFILES = [
    ("AWS/CPU_EC2/CPU.dockerfile", r"^FROM ubuntu:24\.04"),
    (
        "AWS/GPU_EC2/GPU.dockerfile",
        r"^FROM nvidia/cuda:12\.8\.0-runtime-ubuntu24\.04",
    ),
    (
        "AWS/FBPIC_test/FBPIC.dockerfile",
        r"^FROM nvidia/cuda:12\.8\.0-runtime-ubuntu24\.04",
    ),
]


@pytest.mark.parametrize("rel_path,pattern", DOCKERFILES)
def test_dockerfile_base_image(rel_path: str, pattern: str):
    """Ensure each Dockerfile uses the expected base image (first FROM line)."""

    repo_root = Path(__file__).resolve().parents[3]
    dockerfile_path = repo_root / rel_path
    text = dockerfile_path.read_text()

    first_from = next((line for line in text.splitlines() if line.startswith("FROM ")), "")
    assert re.match(pattern, first_from), (
        f"Unexpected base image line in {rel_path}: '{first_from}' does not match '{pattern}'"
    )


@pytest.mark.parametrize("rel_path,_", DOCKERFILES)
def test_dockerfile_has_maintainer_label(rel_path: str, _):  # noqa: D401 unused second arg
    """All Dockerfiles should declare a maintainer label for traceability."""

    repo_root = Path(__file__).resolve().parents[3]
    dockerfile_path = repo_root / rel_path
    text = dockerfile_path.read_text()
    assert "LABEL maintainer=" in text, f"{rel_path} is missing a maintainer LABEL" 