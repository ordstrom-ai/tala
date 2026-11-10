import os
from pathlib import Path
import subprocess
import tempfile
import tomllib

PROJECT_ROOT = Path(__file__).resolve().parent


def check_requirements_file(requirements_file):
    subprocess.run([
        "pur",
        "-r",
        str(requirements_file),
        "--dry-run",
        "--dry-run-changed",
        "--nonzero-exit-code",
    ],
                   cwd=PROJECT_ROOT,
                   check=True)


def check_pyproject_pins():
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pinned_dependencies = [dependency for dependency in project["project"]["dependencies"] if "==" in dependency]
    if not pinned_dependencies:
        return

    with tempfile.TemporaryDirectory(
        prefix="tala-pyproject-dependencies-",
        dir=os.environ.get("RUNNER_TEMP"),
    ) as temporary_directory:
        requirements_file = Path(temporary_directory) / "requirements.txt"
        requirements_file.write_text("\n".join(pinned_dependencies) + "\n", encoding="utf-8")
        check_requirements_file(requirements_file)


def main():
    check_requirements_file(PROJECT_ROOT / "requirements-dev.txt")
    check_pyproject_pins()


if __name__ == "__main__":
    main()
