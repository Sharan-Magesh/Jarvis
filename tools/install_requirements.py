import subprocess
import sys

def install_requirements():
    """Install required packages for LLM integration"""
    packages = [
        "requests",  # For Ollama API calls
        # Your existing packages
        "sounddevice",
        "openai-whisper",
        "pyttsx3",
        "pvporcupine",
        "python-vlc"
    ]
    
    for package in packages:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print(f"✓ Installed {package}")
        except subprocess.CalledProcessError:
            print(f"✗ Failed to install {package}")

if __name__ == "__main__":
    install_requirements()
