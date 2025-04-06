# Everyone AI - Claude Computer Use Demo

A barebones Claude Computer Use demo for macOS. This application allows Claude to interact with your computer, helping you with various tasks by providing it with the ability to see your screen, run terminal commands, and edit files.

## Prerequisites

- Python 3.8+
- macOS (optimized for macOS, but should work on other platforms with minor adjustments)
- [XQuartz](https://www.xquartz.org/) (for GUI applications, optional)
- An Anthropic API key with Computer Use enabled

## Setup

1. Clone this repository
2. Create a virtual environment and activate it:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. If you want to use GUI applications, install XQuartz:
   ```bash
   brew install --cask xquartz
   ```

## Usage

### Terminal Interface

```bash
chmod +x run.py
./run.py
```