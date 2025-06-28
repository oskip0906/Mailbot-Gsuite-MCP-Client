#!/bin/bash

# Create virtual environment
if [ ! -d ".venv" ]; then
    python -m venv .venv
fi

# Activate virtual environment based on OS
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
    # Windows
    source .venv/Scripts/activate
else
    # Linux/macOS
    source .venv/bin/activate
fi

if [ ! -f ".venv/pyvenv.cfg" ] || [ ! -f ".venv/Scripts/pip" ]; then
    python -m pip install -r requirements.txt
fi

cd app

python web_client.py