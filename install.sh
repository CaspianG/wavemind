#!/usr/bin/env sh
set -eu

python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[sentence]"
