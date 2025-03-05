#!/bin/bash

# Create a virtual environment
python3 -m venv magma_env

# Activate the virtual environment
source magma_env/bin/activate

# Upgrade pip
python3 -m pip install --upgrade pip

# Check system and install appropriate dependencies
if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
    echo "Installing for Apple Silicon (MPS)..."
    # Apple Silicon specific installation
    python3 -m pip install torch torchvision
else
    echo "Installing for CUDA compatibility..."
    # CUDA specific installation
    python3 -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
fi

# Install required dependencies from requirements.txt
if [ -f "requirements.txt" ]; then
    echo "Installing dependencies from requirements.txt..."
    python3 -m pip install -r requirements.txt
else
    echo "requirements.txt not found. Installing core dependencies individually..."
    
    # Install required dependencies for Magma-8B
    python3 -m pip install Pillow open_clip_torch requests
    
    # Install the custom transformers library required by Magma-8B
    python3 -m pip install git+https://github.com/jwyang/transformers.git@dev/jwyang-v4.48.2
    
    # Install Gradio for the web interface
    python3 -m pip install gradio matplotlib numpy
fi

# Add these lines in the dependencies section:
python3 -m pip install PyQt5 gradio_client

# Print the installed transformers version
echo "Transformers installed version:"
python3 -m pip show transformers | grep Version

echo "Environment setup complete!"

# Add helper message for activation
echo "To activate this environment in the future, run:"
echo "source magma_env/bin/activate" 