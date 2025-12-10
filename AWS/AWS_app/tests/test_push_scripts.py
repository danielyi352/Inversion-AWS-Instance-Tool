from pathlib import Path
import pytest

# Relative paths (from repository root) to the push scripts we want to test
PUSH_SCRIPTS = [
    "AWS/CPU_EC2/CPU-push-to-ecr.sh",
    "AWS/GPU_EC2/GPU-push-to-ecr.sh",
    "AWS/FBPIC_test/push-to-ecr.sh",
]


@pytest.mark.parametrize("rel_path", PUSH_SCRIPTS)
def test_push_script_contains_docker_commands(rel_path: str):
    """Each push script should build and push a Docker image to ECR."""

    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / rel_path
    text = script_path.read_text()

    assert "docker build" in text, f"{rel_path} does not invoke 'docker build'"
    assert "docker push" in text, f"{rel_path} does not invoke 'docker push'"


@pytest.mark.parametrize("rel_path", PUSH_SCRIPTS)
def test_push_script_has_shebang(rel_path: str):
    """Verify scripts start with a bash shebang (first line)."""

    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / rel_path
    first_line = script_path.read_text().splitlines()[0]
    assert first_line.startswith("#!/"), f"{rel_path} is missing a shebang line" 