#!/usr/bin/env python3
"""
Run script for Claude's computer use terminal client.
Sets required environment variables and handles Python path issues.
"""

import os
import sys
import subprocess

# Default screen resolution if not provided
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 768

def main():
    # Ensure we're in the correct directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # Set required environment variables if not already set
    if not os.environ.get("WIDTH"):
        os.environ["WIDTH"] = str(DEFAULT_WIDTH)
    if not os.environ.get("HEIGHT"):
        os.environ["HEIGHT"] = str(DEFAULT_HEIGHT)
    
    # Set DISPLAY for X11 if on macOS and not already set
    if sys.platform == "darwin" and not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"  # Standard XQuartz display on macOS
        
        # Check if XQuartz is installed
        try:
            xquartz_check = subprocess.run(["xquartz-check"], capture_output=True, text=True)
            if xquartz_check.returncode != 0:
                print("Note: For GUI applications to work properly, XQuartz might need to be installed.")
                print("You can install it with: brew install --cask xquartz")
                print("After installation, you might need to restart this application.")
        except FileNotFoundError:
            # Custom check is not available, try a gentler approach
            if not os.path.exists("/Applications/Utilities/XQuartz.app"):
                print("Note: For GUI applications to work properly, XQuartz might need to be installed.")
                print("You can install it with: brew install --cask xquartz")
                print("After installation, you might need to restart this application.")
    
    # Get API key from environment, command-line, or prompt
    api_key = os.getenv("ANTHROPIC_API_KEY")
    
    # # Check if API key was provided as command-line argument
    # for i, arg in enumerate(sys.argv[1:], 1):
    #     if arg == "--api-key" and i < len(sys.argv):
    #         api_key = sys.argv[i+1]
    #         break
    
    # # If not found in command-line, check environment
    # if not api_key:
    #     api_key = os.environ.get("ANTHROPIC_API_KEY")
        
    # If still not found, prompt user
    if not api_key:
        print("Anthropic API key not found in environment or command line.")
        api_key = input("Please enter your Anthropic API key: ").strip()
        if not api_key:
            print("No API key provided. Exiting.")
            sys.exit(1)
    
    # Set API key environment variable for subprocess
    os.environ["ANTHROPIC_API_KEY"] = api_key
    
    # Print environment variables
    print(f"Running with WIDTH={os.environ['WIDTH']}, HEIGHT={os.environ['HEIGHT']}")
    if os.environ.get("DISPLAY"):
        print(f"DISPLAY={os.environ['DISPLAY']}")
    
    # Run bash.py with Python, keeping any additional arguments
    cmd_args = [sys.executable, "bash.py"]
    
    # Add all command-line arguments except the script name
    cmd_args.extend(sys.argv[1:])
    
    try:
        subprocess.run(cmd_args, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running bash.py: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)

if __name__ == "__main__":
    main() 