from pathlib import Path


def test_sentence_extra_is_available_for_install_scripts():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "sentence = [" in pyproject
    assert '"sentence-transformers>=3"' in pyproject


def test_install_scripts_create_venv_and_install_sentence_extra():
    install_sh = Path("install.sh").read_text(encoding="utf-8")
    install_bat = Path("install.bat").read_text(encoding="utf-8")

    assert "python -m venv .venv" in install_sh
    assert '. .venv/bin/activate' in install_sh
    assert 'pip install -e ".[sentence]"' in install_sh

    assert "python -m venv .venv" in install_bat
    assert r".venv\Scripts\activate.bat" in install_bat
    assert 'pip install -e ".[sentence]"' in install_bat


def test_github_actions_runs_pytest_on_main_for_python_310_and_311():
    workflow = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")

    assert "branches: [main]" in workflow
    assert "3.10" in workflow
    assert "3.11" in workflow
    assert "pytest -q" in workflow
