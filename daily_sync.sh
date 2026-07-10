#!/bin/bash
# Resolve directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Run initialization and sync using the virtual environment python interpreter
.venv/bin/python -c "import app; app.sync_local_to_cloud()"
