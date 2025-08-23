#!/bin/bash

# Create virtual environment
if [ ! -d ".venv" ]; then
	python -m venv .venv
fi

# Activate virtual environment based on OS
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
	source .venv/Scripts/activate
else
	source .venv/bin/activate
fi

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cd app

python web_client.py