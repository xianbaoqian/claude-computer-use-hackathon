#!/bin/bash

# Create a virtual environment
python3 -m venv magma_env

# Activate the virtual environment
source magma_env/bin/activate

# Upgrade pip
python3 -m pip install --upgrade pip

# Install torch and its related packages
python3 -m pip install torch torchvision

# Install required dependencies
python3 -m pip install Pillow open_clip_torch

# Install the custom transformers library required by Magma-8B
python3 -m pip install git+https://github.com/jwyang/transformers.git@dev/jwyang-v4.48.2

# Install requests for downloading images
python3 -m pip install requests

# Print the installed transformers version
echo "Transformers installed version:"
python3 -m pip show transformers | grep Version

echo "Environment setup complete!" 