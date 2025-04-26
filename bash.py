#!/usr/bin/env python3
"""
Terminal-based client for Claude's computer use capabilities.
Simpler alternative to the streamlit interface.
"""

import argparse
import asyncio
import base64
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PosixPath
from typing import Any, cast, get_args

import httpx
from anthropic import Anthropic, RateLimitError
from anthropic.types.beta import (
    BetaContentBlockParam,
    BetaTextBlockParam,
    BetaToolResultBlockParam,
)
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from loop import (
    APIProvider,
    sampling_loop,
)
from tools import ToolResult, ToolVersion

# Initialize console for rich terminal output
console = Console()

@dataclass(kw_only=True, frozen=True)
class ModelConfig:
    tool_version: ToolVersion
    max_output_tokens: int
    default_output_tokens: int
    has_thinking: bool = False

# Claude 3.7 Sonnet configuration
SONNET_3_7 = ModelConfig(
    tool_version="computer_use_20250124",
    max_output_tokens=128_000,
    default_output_tokens=1024 * 16,
    has_thinking=True,
)

# Default model configuration
DEFAULT_MODEL = "claude-3-7-sonnet-20250219"
DEFAULT_MODEL_CONFIG = SONNET_3_7

# Constants for API key storage
CONFIG_DIR = PosixPath("~/.anthropic").expanduser()
API_KEY_FILE = CONFIG_DIR / "api_key"

class Sender(StrEnum):
    USER = "user"
    BOT = "assistant"
    TOOL = "tool"

def load_from_storage(filename: str) -> str | None:
    """Load data from a file in the storage directory."""
    try:
        file_path = CONFIG_DIR / filename
        if file_path.exists():
            data = file_path.read_text().strip()
            if data:
                return data
    except Exception as e:
        console.print(f"Error loading {filename}: {e}", style="red")
    return None

def save_to_storage(filename: str, data: str) -> None:
    """Save data to a file in the storage directory."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        file_path = CONFIG_DIR / filename
        file_path.write_text(data)
        # Ensure only user can read/write the file
        file_path.chmod(0o600)
    except Exception as e:
        console.print(f"Error saving {filename}: {e}", style="red")

async def render_message(sender: Sender, message: str | BetaContentBlockParam | ToolResult) -> None:
    """Display a message in the terminal with appropriate styling."""
    # Check if the message is a tool result
    is_tool_result = not isinstance(message, (str, dict))
    
    if not message:
        return
        
    if sender == Sender.USER:
        console.print(Panel(message, title="User", border_style="blue"))
    elif sender == Sender.BOT:
        if isinstance(message, dict):
            if message["type"] == "text":
                console.print(Panel(Markdown(message["text"]), title="AI", border_style="green"))
            elif message["type"] == "thinking":
                thinking_content = message.get("thinking", "")
                console.print(Panel(Markdown(f"[Thinking]\n\n{thinking_content}"), title="AI (Thinking)", border_style="yellow"))
            elif message["type"] == "tool_use":
                console.print(Panel(f"Tool: {message['name']}\nInput: {message['input']}", title="AI (Tool Use)", border_style="magenta"))
        else:
            console.print(Panel(Markdown(message), title="AI", border_style="green"))
    elif sender == Sender.TOOL:
        if is_tool_result:
            message = cast(ToolResult, message)
            if message.output:
                console.print(Panel(message.output, title="Tool Output", border_style="cyan"))
            if message.error:
                console.print(Panel(message.error, title="Tool Error", border_style="red"))
            if message.base64_image:
                console.print("[Image output available but not displayed in terminal]")
        else:
            console.print(Panel(str(message), title="Tool Result", border_style="cyan"))

def api_response_callback(
    request: httpx.Request,
    response: httpx.Response | object | None,
    error: Exception | None,
) -> None:
    """Handle API responses and errors."""
    if error:
        if isinstance(error, RateLimitError):
            retry_after = error.response.headers.get("retry-after", "unknown")
            console.print(f"Rate limited. Retry after: {retry_after} seconds", style="red")
        else:
            console.print(f"Error: {error}", style="red")

async def tool_output_callback(tool_output: ToolResult, tool_id: str):
    """Handle tool output by rendering it."""
    await render_message(Sender.TOOL, tool_output)

async def main():
    """Main function for the terminal-based Claude client."""
    parser = argparse.ArgumentParser(description="Terminal-based client for Claude's computer use capabilities")
    parser.add_argument("--api-key", help="Anthropic API key (will be saved for future use)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model name (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MODEL_CONFIG.default_output_tokens, 
                        help=f"Maximum output tokens (default: {DEFAULT_MODEL_CONFIG.default_output_tokens})")
    parser.add_argument("--thinking", action="store_true", help="Enable thinking mode (Claude 3.7+ only)")
    parser.add_argument("--thinking-budget", type=int, help="Thinking token budget (Claude 3.7+ only)")
    parser.add_argument("--system-prompt", help="Additional system prompt instructions")
    parser.add_argument("--recent-images", type=int, default=3, 
                        help="Only send N most recent images (default: 3, 0 for unlimited)")
    
    args = parser.parse_args()
    
    # Load or save API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("Error: No API key provided. Use --api-key or set ANTHROPIC_API_KEY environment variable.", style="red")
        sys.exit(1)
    
    if args.api_key:
        save_to_storage("api_key", args.api_key)
    
    # Configure model
    model = args.model
    tool_version = DEFAULT_MODEL_CONFIG.tool_version
    max_tokens = args.max_tokens
    thinking_budget = args.thinking_budget if args.thinking else None
    only_n_most_recent_images = args.recent_images
    system_prompt = args.system_prompt or ""
    
    # Add macOS specific system prompt content if running on macOS
    if sys.platform == "darwin":
        system_prompt += "\n\nYou are running on macOS. Use macOS-specific commands and tools when appropriate. For package management, use brew instead of apt. Terminal applications may behave differently than on Linux."
    
    messages = []
    
    console.print(Panel.fit(
        "Computer Use Terminal Client\nType your message or 'exit' to quit", 
        title="Welcome", 
        border_style="green"
    ))
    
    try:
        while True:
            # Get user input
            console.print("\n[bold blue]You:[/bold blue] ", end="")
            user_input = input()
            
            if user_input.lower() in ("exit", "quit"):
                break
            
            # Add user message to conversation
            messages.append({
                "role": Sender.USER,
                "content": [BetaTextBlockParam(type="text", text=user_input)],
            })
            await render_message(Sender.USER, user_input)
            
            # Process with Claude
            messages = await sampling_loop(
                system_prompt_suffix=system_prompt,
                model=model,
                provider=APIProvider.ANTHROPIC,
                messages=messages,
                output_callback=lambda content: render_message(Sender.BOT, content),
                tool_output_callback=tool_output_callback,
                api_response_callback=api_response_callback,
                api_key=api_key,
                only_n_most_recent_images=only_n_most_recent_images,
                tool_version=tool_version,
                max_tokens=max_tokens,
                thinking_budget=thinking_budget,
                token_efficient_tools_beta=True,
            )
            
    except KeyboardInterrupt:
        console.print("\nExiting...", style="yellow")
    except Exception as e:
        console.print(f"\nError: {e}", style="red")

if __name__ == "__main__":
    asyncio.run(main()) 