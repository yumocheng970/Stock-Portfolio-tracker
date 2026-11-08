#!/usr/bin/env bash
# Setup for macOS / Linux / WSL: creates the conda environment "spt" if it is
# missing, then runs the setup wizard (python -m setup) in it.
# It does NOT install PostgreSQL or Miniforge (see README.md -> Quick start).
set -euo pipefail
cd "$(dirname "$0")"                      # the project folder, wherever this is started from

if ! command -v conda >/dev/null 2>&1; then
    echo "conda was not found. Install Miniforge first: https://github.com/conda-forge/miniforge"
    echo "(then open a new terminal and run ./setup.sh again)"
    exit 1
fi

if conda env list | grep -qE '^spt[[:space:]]'; then
    echo "The conda environment 'spt' exists."
else
    echo "Creating the conda environment 'spt' from environment.yml (about a minute) ..."
    conda env create -f environment.yml
fi

# --no-capture-output: show the wizard's questions and let you type the answers
exec conda run --no-capture-output -n spt python -m setup "$@"
