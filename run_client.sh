#!/bin/bash
cd app

if [ ! -d ".venv" ]; then
    python -m venv .venv
fi

source .venv/Scripts/activate

if [ ! -f ".venv/pyvenv.cfg" ] || [ ! -f ".venv/Scripts/pip" ]; then
    python -m pip install -r requirements.txt
fi

python web_client.py