#!/bin/bash

# Create virtual environment
python3 -m venv resemble_env
source resemble_env/bin/activate

# Install packages from requirements.txt
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Virtual environment setup complete!"
echo "To activate, run: source resemble_env/bin/activate"
echo "To test TTS, run: python resemble_pipecat_tts.py"