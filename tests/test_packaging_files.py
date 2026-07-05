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
    optional_requirements = Path("requirements-optional.txt").read_text(
        encoding="utf-8"
    )

    assert "otel = [" in pyproject
    assert '"opentelemetry-sdk>=1.25"' in pyproject
    assert "opentelemetry-sdk>=1.25" in optional_requirements
    assert "opentelemetry-exporter-otlp>=1.25" in optional_requirements
    assert "opentelemetry-instrumentation-fastapi>=0.46b0" in optional_requirements
    assert "production = [" in pyproject
    assert '"opentelemetry-instrumentation-fastapi>=0.46b0"' in pyproject
    assert "s3 = [" in pyproject
    assert '"boto3>=1.34"' in pyproject
    assert "boto3>=1.34" in optional_requirements


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
    editable_install = "pip install --no-cache-dir -e"

    assert readme_copy in dockerfile
    assert dockerfile.index(readme_copy) < dockerfile.index(editable_install)
    assert "ARG INSTALL_PRODUCTION=false" in dockerfile
    assert "build-essential" in dockerfile


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
    readme = Path("README.md").read_text(encoding="utf-8")
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    use_cases = Path("docs/USE_CASES.md").read_text(encoding="utf-8")
    chroma_migration = Path("docs/CHROMA_MIGRATION.md").read_text(encoding="utf-8")
    launch_kit = Path("docs/LAUNCH_KIT.md").read_text(encoding="utf-8")
    benchmark_brief = Path("docs/BENCHMARK_BRIEF.md").read_text(encoding="utf-8")

    assert "include CONTRIBUTING.md" in manifest
    assert "include SECURITY.md" in manifest
    assert "include SUPPORT.md" in manifest
    assert "include docs/ROADMAP.md" in manifest
    assert "include docs/RELEASE.md" in manifest
    assert "include docs/PROJECT_BOARD.md" in manifest
    assert "include docs/BENCHMARK_BRIEF.md" in manifest
    assert "include docs/CHROMA_MIGRATION.md" in manifest
    assert "include docs/OBSERVABILITY.md" in manifest
    assert "include docs/assets/benchmark-summary.svg" in manifest
    assert "include benchmarks/*.json" in manifest
    assert "include docs/assets/wavemind-demo.gif" in manifest
    assert "include examples/*.py" in manifest
    assert "recursive-include examples/observability *" in manifest
    assert "recursive-include examples/production-index-profile *" in manifest
    assert "recursive-include deploy/helm/wavemind *" in manifest
    assert "prune benchmarks/data" in manifest
    assert "docs/CHROMA_MIGRATION.md" in readme
    assert "docs/BENCHMARK_BRIEF.md" in readme
    assert "examples/chroma_migration.py" in readme
    assert "examples/customer_support_memory.py" in readme
    assert "examples/research_notebook_memory.py" in readme
    assert "docs/assets/wavemind-demo.gif" in readme
    assert Path("docs/assets/wavemind-demo.gif").exists()
    assert "docs/OBSERVABILITY.md" in readme
    assert "deploy/helm/wavemind" in readme
    assert "cluster-repair` CronJob" in readme
    assert "wavemind scale-plan --target-memories 50000" in readme
    assert "--fail-on action_required" in readme
    assert "GET /scale-plan" in roadmap
    assert "/scale-plan?target_memories=50000" in readme
    assert "wavemind consolidate" in readme
    assert "POST /consolidate" in readme
    assert "consolidate_concepts" in readme
    assert "scale-plan" in roadmap
    assert "consolidate_concepts" in roadmap
    assert "scale-plan" in use_cases
    assert "consolidate_concepts" in use_cases
    assert "Keep Chroma as-is" in chroma_migration
    assert "WaveMind is not a faster Chroma replacement" in chroma_migration
    assert "examples/chroma_migration.py" in chroma_migration
    assert "namespace=\"user:42\"" in chroma_migration
    assert "docs/BENCHMARK_BRIEF.md" in launch_kit
    assert "examples/customer_support_memory.py" in launch_kit
    assert "examples/research_notebook_memory.py" in launch_kit
    assert "checked-in JSON artifacts" in benchmark_brief
    assert "Static vector search is still faster" in benchmark_brief
