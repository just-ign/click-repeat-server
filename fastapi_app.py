from fastapi import FastAPI, WebSocket
import os
from loop import sampling_loop, APIProvider
from anthropic.types.beta import BetaTextBlockParam

app = FastAPI()

async def output_callback(content, websocket):
    if content["type"] == "text":
        await websocket.send_text(content["text"])
    elif content["type"] == "thinking":
        await websocket.send_text(f"[Thinking] {content.get('thinking', '')}")

async def tool_output_callback(tool_output, tool_id, websocket):
    if tool_output.output:
        await websocket.send_text(f"Tool Output: {tool_output.output}")
    if tool_output.error:
        await websocket.send_text(f"Tool Error: {tool_output.error}")

def api_response_callback(request, response, error, websocket):
    if error:
        websocket.send_text(f"API Error: {error}")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    messages = []
    api_key = "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"
    model = "claude-3-7-sonnet-20250219"
    tool_version = "computer_use_20250124"
    max_tokens = 1024 * 16
    thinking_budget = None
    only_n_most_recent_images = 3
    system_prompt = "You are running on macOS. Use macOS-specific commands and tools when appropriate. For package management, use brew instead of apt. Terminal applications may behave differently than on Linux."

    try:
        while True:
            data = await websocket.receive_text()
            messages.append({
                "role": "user",
                "content": [BetaTextBlockParam(type="text", text=data)],
            })

            # Process with sampling_loop
            messages = await sampling_loop(
                system_prompt_suffix=system_prompt,
                model=model,
                provider=APIProvider.ANTHROPIC,
                messages=messages,
                output_callback=lambda content: output_callback(content, websocket),
                tool_output_callback=lambda tool_output, tool_id: tool_output_callback(tool_output, tool_id, websocket),
                api_response_callback=lambda request, response, error: api_response_callback(request, response, error, websocket),
                api_key=api_key,
                only_n_most_recent_images=only_n_most_recent_images,
                tool_version=tool_version,
                max_tokens=max_tokens,
                thinking_budget=thinking_budget,
                token_efficient_tools_beta=True,
            )
    except Exception as e:
        print(f"WebSocket connection closed: {e}")
    finally:
        await websocket.close() 