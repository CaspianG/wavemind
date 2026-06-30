from pathlib import Path
import re

import wavemind


def test_package_version_matches_pyproject():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, flags=re.MULTILINE)

    assert match is not None
    assert wavemind.__version__ == match.group(1)


def test_sentence_extra_is_available_for_install_scripts():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "sentence = [" in pyproject
    assert '"sentence-transformers>=3"' in pyproject


def test_benchmark_extra_installs_chroma():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "bench = [" in pyproject
    assert '"chromadb>=1.0"' in pyproject


def test_postgres_extra_installs_psycopg_for_pgvector():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "postgres = [" in pyproject
    assert '"psycopg[binary]>=3.1"' in pyproject


def test_indexes_extra_installs_qdrant_client():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    optional_requirements = Path("requirements-optional.txt").read_text(
        encoding="utf-8"
    )

    assert "indexes = [" in pyproject
    assert '"qdrant-client>=1.9"' in pyproject
    assert "qdrant-client>=1.9" in optional_requirements


def test_otel_and_production_extras_are_available():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "otel = [" in pyproject
    assert '"opentelemetry-sdk>=1.25"' in pyproject
    assert "production = [" in pyproject
    assert '"opentelemetry-instrumentation-fastapi>=0.46b0"' in pyproject


def test_langchain_extra_installs_classic_memory_api():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "langchain = [" in pyproject
    assert '"langchain-classic>=1.0"' in pyproject


def test_dev_extra_runs_against_real_langchain_memory_api():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    integration = Path("wavemind/integrations/langchain.py").read_text(
        encoding="utf-8"
    )

    assert "dev = [" in pyproject
    assert '"langchain-classic>=1.0"' in pyproject
    assert "class BaseMemory" not in integration
    assert 'pip install "wavemind[langchain]"' in integration


def test_install_scripts_create_venv_and_install_sentence_extra():
    install_sh = Path("install.sh").read_text(encoding="utf-8")
    install_bat = Path("install.bat").read_text(encoding="utf-8")

    assert "python -m venv .venv" in install_sh
    assert '. .venv/bin/activate' in install_sh
    assert 'pip install -e ".[sentence]"' in install_sh

    assert "python -m venv .venv" in install_bat
    assert r".venv\Scripts\activate.bat" in install_bat
    assert 'pip install -e ".[sentence]"' in install_bat


def test_docker_files_track_runtime_package_version():
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "pytest" not in requirements
    assert "httpx" not in requirements
    assert f"image: wavemind:{wavemind.__version__}" in compose


def test_dockerfile_copies_readme_before_editable_install():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    readme_copy = "COPY README.md pyproject.toml requirements.txt requirements-optional.txt ./"
    editable_install = "RUN pip install --no-cache-dir -e ."

    assert readme_copy in dockerfile
    assert dockerfile.index(readme_copy) < dockerfile.index(editable_install)


def test_github_actions_runs_pytest_on_main_for_python_310_and_311():
    workflow = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")

    assert "branches: [main]" in workflow
    assert "3.10" in workflow
    assert "3.11" in workflow
    assert "pytest -q" in workflow


def test_release_workflow_builds_and_creates_github_release():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert 'tags:' in workflow
    assert '"v*"' in workflow
    assert "python -m build" in workflow
    assert "python -m twine check dist/*" in workflow
    assert "softprops/action-gh-release" in workflow


def test_manifest_includes_docs_without_large_benchmark_data():
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")

    assert "include CONTRIBUTING.md" in manifest
    assert "include SECURITY.md" in manifest
    assert "include SUPPORT.md" in manifest
    assert "include docs/ROADMAP.md" in manifest
    assert "include docs/RELEASE.md" in manifest
    assert "include docs/PROJECT_BOARD.md" in manifest
    assert "include docs/assets/benchmark-summary.svg" in manifest
    assert "include benchmarks/*.json" in manifest
    assert "include examples/*.py" in manifest
    assert "prune benchmarks/data" in manifest
