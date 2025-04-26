from fastapi import FastAPI, WebSocket
import os
import json
import logging
from loop import sampling_loop, APIProvider
from anthropic.types.beta import BetaTextBlockParam
from tools import ToolResult
import recorder  # Import the recorder module
import threading
from video_processing import generate

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()

# Check for DEBUG environment variable
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
logger.info(f"Tool execution mode: {'SERVER-SIDE (DEBUG=True)' if DEBUG else 'CLIENT-SIDE (DEBUG=False)'}")

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

async def client_side_tool_execution(tool_name, tool_input, tool_id, websocket):
    # Determine tool type based on name
    tool_type = ""
    if tool_name == "computer":
        tool_type = "computer"
    elif tool_name == "str_replace_editor":
        tool_type = "text_editor"
    elif tool_name == "bash":
        tool_type = "bash"
    
    # Send tool call to client
    tool_call = {
        "action": "tool_call",
        "tool_name": tool_name,
        "tool_type": tool_type,
        "tool_input": tool_input,
        "tool_id": tool_id
    }
    
    logger.info(f"Sending tool call to client: {tool_name} ({tool_type}) with ID: {tool_id}")
    logger.debug(f"Tool input: {json.dumps(tool_input)[:200]}...")
    await websocket.send_json(tool_call)
    
    # Wait for client response
    logger.info(f"Waiting for client response for tool: {tool_name}")
    response = await websocket.receive_json()
    logger.info(f"Received client response for tool: {tool_name}")
    
    if response.get("error"):
        logger.error(f"Client reported error for {tool_name}: {response.get('error')[:200]}...")
    
    # Parse response into ToolResult
    return ToolResult(
        output=response.get("output", ""),
        error=response.get("error", ""),
        base64_image=response.get("base64_image", None),
        system=response.get("system", None)
    )

# Custom run function for tool collection that redirects execution to client
async def custom_tool_run(tool_collection, name, tool_input, tool_id, websocket):
    if DEBUG:
        # Use the original run method when DEBUG is true
        return await tool_collection.run(name=name, tool_input=tool_input)
    else:
        # Redirect to client-side execution with the tool_id
        return await client_side_tool_execution(name, tool_input, tool_id, websocket)

@app.post("/start_recording")
def start_recording_endpoint():
    """Start screen, audio, and interaction recording in a non-blocking way"""
    try:
        # Start recording in a separate thread to avoid blocking
        recording_thread = threading.Thread(target=recorder.start_recording)
        recording_thread.daemon = True  # Thread will exit when main program exits
        recording_thread.start()
        logger.info("Recording started in background thread")
        return {"status": "success", "message": "Recording started successfully in the background"}
    except Exception as e:
        logger.error(f"Error starting recording: {str(e)}")
        return {"status": "error", "message": f"Failed to start recording: {str(e)}"}

@app.post("/stop_recording")
def stop_recording_endpoint():
    """Stop ongoing recording and save results"""
    try:
        # Call the stop_recording function from the recorder module
        out_dir = recorder.stop_recording()
        print("Processing video...")
        generate(out_dir)
        return {"status": "success", "message": "Recording stopped and saved successfully", "out_dir": out_dir}
    except Exception as e:
        logger.error(f"Error stopping recording: {str(e)}")
        return {"status": "error", "message": f"Failed to stop recording: {str(e)}"}

@app.get("/workflows")
async def get_workflow():
    import os
    import json

    workflows = []
    recordings_dir = os.path.join(os.getcwd(), "recordings")
    
    # Iterate through all session directories in the recordings folder
    for session_dir in os.listdir(recordings_dir):
        session_path = os.path.join(recordings_dir, session_dir)
        
        # Check if it's a directory
        if os.path.isdir(session_path):
            workflow_file = os.path.join(session_path, "workflow_structured.json")
            
            # Check if the workflow_structured.json file exists
            if os.path.exists(workflow_file):
                try:
                    with open(workflow_file, 'r') as f:
                        workflow_content = f.read()
                        workflows.append(json.loads(workflow_content))
                except Exception as e:
                    logger.error(f"Error reading workflow file {workflow_file}: {str(e)}")
    
    return {"status": "success", "message": "Workflow retrieved successfully", "workflows": workflows}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_host = websocket.client.host
    client_port = websocket.client.port
    client_id = f"{client_host}:{client_port}"
    
    logger.info(f"New WebSocket connection from {client_id}")
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for {client_id}")
    
    messages = []
    api_key = "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"
    model = "claude-3-7-sonnet-20250219"
    tool_version = "computer_use_20250124"
    max_tokens = 1024 * 16
    thinking_budget = None
    only_n_most_recent_images = 3
    system_prompt = "You are running on macOS. Use macOS-specific commands and tools when appropriate. For package management, use brew instead of apt. Terminal applications may behave differently than on Linux."

    try:
        # Send initial connection message with debug status
        await websocket.send_json({
            "action": "connection_status",
            "client_id": client_id,
            "status": "connected",
            "debug_mode": DEBUG
        })
        logger.info(f"Sent connection status to {client_id}")
        
        while True:
            logger.info(f"Waiting for message from {client_id}")
            data = await websocket.receive_text()
            logger.info(f"Received message from {client_id}: {data[:50]}...")
            
            messages.append({
                "role": "user",
                "content": [BetaTextBlockParam(type="text", text=data)],
            })

            # Process with sampling_loop
            logger.info(f"Starting sampling loop for {client_id}")
            try:
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
                    custom_tool_run=None if DEBUG else lambda tool_collection, name, tool_input, tool_id: custom_tool_run(tool_collection, name, tool_input, tool_id, websocket),
                )
                logger.info(f"Completed sampling loop for {client_id}")
            except Exception as e:
                logger.error(f"Error in sampling loop for {client_id}: {str(e)}")
                await websocket.send_json({
                    "action": "error",
                    "error": f"Server error: {str(e)}"
                })
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {str(e)}")
    finally:
        try:
            await websocket.send_json({
                "action": "connection_status",
                "client_id": client_id,
                "status": "disconnected"
            })
        except Exception:
            pass
        
        logger.info(f"WebSocket connection closed for {client_id}")
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 