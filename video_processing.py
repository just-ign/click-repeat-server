# To run this code you need to install the following dependencies:
# pip install google-genai

from time import sleep
import base64
import os
import json
import argparse
from pathlib import Path
from google import genai
from google.genai import types


DEFAULT_SESSION_PATH = "recordings/session_2025-04-25_22-07-41"

prompt = """Based on the screen recording and the provided JSON data, analyze the user's workflow and provide a structured JSON response in EXACTLY the following format:

```json
{
    "Title": "Brief descriptive title of the workflow",
    "Steps": [
        "First step with specific action",
        "Second step with specific action",
        "Continue with more steps..."
    ],
    "Important Input Text Fields": [
        {
            "Field": "Field name",
            "Value": "Exact value of what needs to be entered, Can be edited later by the user"
        }
    ]
}
```

Make sure to focus on concrete actions that can be programmatically recreated. Be specific about what the user did rather than what was visible on screen. The response MUST be valid JSON that can be parsed.
Ignore the last few steps that's involved in stopping the video recording'.
"""


def load_json_file(file_path):
    """Load and return the contents of a JSON file"""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON file {file_path}: {e}")
        return None

def generate(session_path=DEFAULT_SESSION_PATH, api_key=None):
    # Convert to Path object if it's a string
    if isinstance(session_path, str):
        session_path = Path(session_path)
    
    # Ensure the session path exists
    if not session_path.exists():
        print(f"Error: Session path {session_path} does not exist")
        return
    
    # Find the video file (should be an .mp4 file)
    video_files = list(session_path.glob("*.mp4"))
    if not video_files:
        print(f"Error: No video file found in {session_path}")
        return
    video_file = video_files[0]
    
    # Find the JSON files
    semantic_actions_file = session_path / "semantic_actions.json"
    workflow_file = session_path / "workflow.json"
    
    # Check if JSON files exist
    if not semantic_actions_file.exists() or not workflow_file.exists():
        print(f"Error: Required JSON files not found in {session_path}")
        return
    
    # Load JSON data
    semantic_actions = load_json_file(semantic_actions_file)
    workflow = load_json_file(workflow_file)
    
    if not semantic_actions or not workflow:
        print("Error loading JSON data")
        return
    
    # Initialize Gemini client
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
    
    client = genai.Client(api_key=api_key)
    
    print(f"Uploading video file: {video_file}...")
    uploaded_file = client.files.upload(file=str(video_file))
    print("Uploaded video file successfully")
    
    # Wait and check file status
    max_retries = 10
    retry_count = 0
    while retry_count < max_retries:
        file_status = client.files.get(name=uploaded_file.name)
        if file_status.state == "ACTIVE":
            print("File is ready for processing...")
            break
        elif file_status.state == "FAILED":
            print("File processing failed!")
            client.files.delete(name=uploaded_file.name)
            return
        print("File is still processing... waiting")
        sleep(3)
        retry_count += 1
    
    if retry_count >= max_retries:
        print("Timeout waiting for file to be ready")
        client.files.delete(name=uploaded_file.name)
        return

    try:
        model = "models/gemini-2.5-pro-exp-03-25"
        
        # Convert JSON data to formatted strings
        semantic_actions_str = json.dumps(semantic_actions, indent=2)
        workflow_str = json.dumps(workflow, indent=2)
        
        # Create a combined prompt with JSON data
        combined_prompt = f"{prompt}\n\n--- SEMANTIC ACTIONS JSON ---\n{semantic_actions_str}\n\n--- WORKFLOW JSON ---\n{workflow_str}\n\nIMPORTANT: Your response MUST be valid JSON that matches the format shown above. Do not include any text outside the JSON structure."
        
        contents = [
            # First add the video file
            types.Content(
                role="user",
                parts=[
                    types.Part.from_uri(
                        file_uri=uploaded_file.uri,
                        mime_type=uploaded_file.mime_type,
                    ),
                ],
            ),
            # Then add the prompt with JSON data
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=combined_prompt),
                ],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            response_mime_type="text/plain",
        )

        print("Generating content...")
        response_text = ""
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            chunk_text = chunk.text
            response_text += chunk_text
            print(chunk_text, end="")
        
        # Try to extract and save the JSON response
        try:
            # Look for JSON between triple backticks if present
            import re
            json_match = re.search(r'```json\s*(.+?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Otherwise try to parse the whole response as JSON
                json_str = response_text
            
            # Parse and format the JSON
            workflow_json = json.loads(json_str)
            
            # Save the structured JSON to a file
            output_file = session_path / "workflow_structured.json"
            with open(output_file, 'w') as f:
                json.dump(workflow_json, f, indent=2)
            
            print(f"\n\nStructured workflow saved to {output_file}")
        except Exception as e:
            print(f"\n\nError parsing JSON response: {e}")
    finally:
        # Clean up by deleting the file
        print("\nCleaning up...")
        client.files.delete(name=uploaded_file.name)
        print("File deleted successfully")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process recording session and analyze with Gemini")
    parser.add_argument(
        "--session", 
        type=str, 
        default=DEFAULT_SESSION_PATH,
        help=f"Path to the recording session folder (default: {DEFAULT_SESSION_PATH})"
    )
    parser.add_argument(
        "--api-key", 
        type=str, 
        help="Gemini API key (if not provided, will use GEMINI_API_KEY environment variable or default key)"
    )
    
    args = parser.parse_args()
    generate(session_path=args.session, api_key=args.api_key)
