# Click Repeat

ClickRepeat — Automate Any Desktop Task in Seconds (clickrepeat.com)

What's the pain?
Endless clicking, typing, copying pasting all these tiny jobs add up to hours of boring work. Creating RPA automations for each task is not scalable and requires coding knowledge making it unaccessible for most people.

What we're building:
A tool that watches you work, turns your actions into a repeatable "script," and then runs it for you—either on your own computer or up in the cloud.

How it works:
1. Record on your PC (screen recording + OS accessibility API for deep integration)
2. AI makes a playbook (auto-generates each step and the fields you need)
3. Run anywhere
    - Local mode on your machine for instant runs
    - Cloud mode on our Mac Minis in AWS (with hardware-acceleration so we leverage the full performance of Apple Silicon)

Why our solution works:
1. No coding—just click "Record," do your thing, then click "Play."
2. Switch between local or cloud with one toggle.
3. Secure, isolated runs so your data stays private.

Hackathon plan:
1. Get a basic record→replay loop.
2. Build the step-extractor (playbook creator).
3. Spin up one Mac Mini on AWS and run a test job.
4. Show a simple UI where you can create and run your workflow.


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