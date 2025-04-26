import subprocess
import platform
import datetime
import pathlib
import signal
import json
import time
import threading
import os
import re
import pyautogui
from rich.console import Console
from pynput import keyboard, mouse

# macOS specific imports
import Cocoa
import objc
from Foundation import NSMakeRect

# Import the specific PyObjC frameworks we need
from AppKit import NSWorkspace, NSScreen, NSEvent, NSApplication
from Quartz import (CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, 
                    kCGNullWindowID, kCGWindowName, kCGWindowOwnerName, kCGWindowNumber,
                    kCGWindowBounds, CGDisplayBounds, CGMainDisplayID)

c = Console()
base_dir = pathlib.Path("recordings")
base_dir.mkdir(exist_ok=True)

# Global variables for tracking input events
recording = False
actions = []

# Text input tracking
current_text_field = None
current_text_buffer = ""
last_element_info = None

mouse_listener = None
keyboard_listener = None
recording_proc = None
out_dir = None

# Command key tracking
command_key_pressed = False
shift_key_pressed = False
control_key_pressed = False
option_key_pressed = False

# Special key mapping
SPECIAL_KEYS = {
    keyboard.Key.enter: "enter",
    keyboard.Key.tab: "tab",
    keyboard.Key.space: "space",
    keyboard.Key.backspace: "backspace",
    keyboard.Key.delete: "delete",
    keyboard.Key.esc: "escape",
    keyboard.Key.up: "up",
    keyboard.Key.down: "down",
    keyboard.Key.left: "left",
    keyboard.Key.right: "right",
    keyboard.Key.home: "home",
    keyboard.Key.end: "end",
    keyboard.Key.page_up: "page_up",
    keyboard.Key.page_down: "page_down",
    keyboard.Key.cmd: "command",
    keyboard.Key.ctrl: "control",
    keyboard.Key.shift: "shift",
    keyboard.Key.alt: "option",
}

# Track active application
active_app = None
active_window_title = None

# Track clipboard content for paste operations
last_clipboard_content = None

def ffmpeg_cmd(out_dir):
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    outfile = out_dir / f"capture_{ts}.mp4"
    sys = platform.system()

    if sys == "Darwin":  # macOS
        # First, list available devices to help with debugging
        c.print("[bold yellow]Available AVFoundation devices:[/]")
        os.system("ffmpeg -f avfoundation -list_devices true -i """)
        
        # Use combined input for better sync - capture both screen and audio in one command
        # Format is "VIDEO_DEVICE:AUDIO_DEVICE" - using 1 for screen and 0 for built-in mic
        video_audio_in = "-f avfoundation -framerate 30 -capture_cursor 1 -i 1:0"
        
        # Simple audio filters to avoid syntax errors
        audio_filters = "volume=1.5"
        
        # No separate audio input needed
        audio_in = ""
    elif sys == "Windows":  # Windows 10/11
        video_in = "-f gdigrab -framerate 30 -i desktop"
        audio_in = "-f dshow -i audio=\"virtual-audio-capturer\""
        audio_filters = "highpass=f=100,lowpass=f=12000,afftdn=nr=97:nf=-50:tn=1,volume=1.5"
    else:  # Linux (X11 + PulseAudio)
        video_in = "-f x11grab -framerate 30 -i :0.0"
        audio_in = "-f pulse -i default"
        audio_filters = "highpass=f=100,lowpass=f=12000,afftdn=nr=97:nf=-50:tn=1,volume=1.5"

    # High quality encoding settings - use a supported pixel format for macOS
    video_codec = "-c:v libx264 -preset veryfast -pix_fmt nv12 -crf 23"
    audio_codec = "-c:a aac -b:a 192k"
    
    if sys == "Darwin":
        # Use the combined video/audio input for macOS
        return f"ffmpeg {video_audio_in} {video_codec} -af {audio_filters} {audio_codec} \"{outfile}\"", outfile
    else:
        return f"ffmpeg {video_in} {audio_in} {video_codec} -af {audio_filters} {audio_codec} \"{outfile}\"", outfile

def get_window_at_position(x, y):
    """Get window information at the given screen coordinates using CGWindowListCopyWindowInfo"""
    global active_window_title, active_app
    
    # Get all on-screen windows
    window_list = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    
    for window in window_list:
        # Get window bounds
        bounds_dict = window.get(kCGWindowBounds)
        if not bounds_dict:
            continue
        
        # Check if point is within window bounds
        x_min = bounds_dict['X']
        y_min = bounds_dict['Y']
        width = bounds_dict['Width']
        height = bounds_dict['Height']
        
        if (x_min <= x <= x_min + width) and (y_min <= y <= y_min + height):
            # Found a window containing the point
            app_name = window.get(kCGWindowOwnerName, 'Unknown')
            window_title = window.get(kCGWindowName, '')
            window_id = window.get(kCGWindowNumber, 0)
            
            # Update global tracking variables
            active_window_title = window_title
            
            element_info = {
                'role': 'window',
                'application': app_name,
                'title': window_title,
                'window_id': window_id,
                'bounds': {
                    'x': x_min,
                    'y': y_min,
                    'width': width,
                    'height': height
                }
            }
            
            # Try to extract more semantic information from the window title
            if window_title:
                # Look for common UI patterns in window titles
                if ' - ' in window_title:
                    # Many apps use format "Document - Application"
                    element_info['document'] = window_title.split(' - ')[0]
                
                # Check for common dialog patterns
                dialog_types = ['Save', 'Open', 'Print', 'Preferences', 'Settings', 'Properties', 'About']
                for dialog in dialog_types:
                    if dialog in window_title:
                        element_info['dialog_type'] = dialog
                        break
            
            return element_info
    
    return None

def get_active_application_info():
    """Get information about the currently active application"""
    global active_app
    
    # Get the frontmost application
    workspace = NSWorkspace.sharedWorkspace()
    frontmost_app = workspace.frontmostApplication()
    
    if frontmost_app:
        app_info = {
            'application': frontmost_app.localizedName(),
            'bundle_id': frontmost_app.bundleIdentifier(),
            'executable': frontmost_app.executableURL().path()
        }
        
        # Update global tracking variable
        active_app = app_info['application']
        
        # Add application category information if possible
        bundle_id = app_info['bundle_id']
        if bundle_id:
            if bundle_id.startswith('com.apple'):
                app_info['category'] = 'Apple System App'
            elif any(term in bundle_id for term in ['browser', 'chrome', 'safari', 'firefox', 'edge']):
                app_info['category'] = 'Web Browser'
            elif any(term in bundle_id for term in ['editor', 'code', 'studio', 'ide']):
                app_info['category'] = 'Code Editor'
            elif any(term in bundle_id for term in ['terminal', 'iterm', 'console']):
                app_info['category'] = 'Terminal'
        
        return app_info
    
    return None

def update_active_window_info():
    """Update information about the currently active window"""
    global active_window_title, active_app
    
    # Get all on-screen windows
    window_list = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    
    # The first window in the list is typically the frontmost one
    if window_list and len(window_list) > 0:
        frontmost_window = window_list[0]
        active_window_title = frontmost_window.get(kCGWindowName, '')
        active_app = frontmost_window.get(kCGWindowOwnerName, 'Unknown')
        
        return {
            'title': active_window_title,
            'application': active_app,
            'window_id': frontmost_window.get(kCGWindowNumber, 0)
        }
    
    return None

def get_clipboard_content():
    """Get the current clipboard content"""
    try:
        return pyautogui.paste()
    except Exception:
        return None

def on_mouse_click(x, y, button, pressed):
    """Callback function for mouse click events with semantic information"""
    global recording, actions, last_element_info, current_text_field, current_text_buffer
    global command_key_pressed, shift_key_pressed, control_key_pressed, option_key_pressed
    global last_clipboard_content
    
    if not recording or not pressed:  # Only capture on press, not release
        return
    
    # Flush any pending text input if we're clicking away from a text field
    if current_text_field and current_text_buffer:
        actions.append({
            "timestamp": time.time(),
            "action": "text_input",
            "element": current_text_field,
            "text": current_text_buffer,
            "application": active_app,
            "window_title": active_window_title
        })
        current_text_buffer = ""
        current_text_field = None
    
    # Get information about the window at click position
    window_info = get_window_at_position(x, y)
    
    # Get active application info
    app_info = get_active_application_info()
    
    # Combine information
    element_info = {}
    if window_info:
        element_info.update(window_info)
    if app_info:
        # Only update application if not already set by window_info
        if 'application' not in element_info and 'application' in app_info:
            element_info['application'] = app_info['application']
        element_info['app_details'] = app_info
    
    # If we couldn't get any element info, create basic info
    if not element_info:
        element_info = {
            'role': 'unknown',
            'application': active_app or 'unknown',
            'window_title': active_window_title or ''
        }
    
    last_element_info = element_info
    
    # Check for modifier keys
    modifiers = []
    if command_key_pressed:
        modifiers.append("command")
    if shift_key_pressed:
        modifiers.append("shift")
    if control_key_pressed:
        modifiers.append("control")
    if option_key_pressed:
        modifiers.append("option")
    
    # Record action with available information
    action_data = {
        "timestamp": time.time(),
        "action": "click",
        "element": element_info,
        "x": x,
        "y": y,
        "button": str(button),
        "application": active_app or element_info.get('application', 'unknown'),
        "window_title": active_window_title or element_info.get('title', '')
    }
    
    # Add modifiers if present
    if modifiers:
        action_data["modifiers"] = modifiers
    
    # Try to determine more specific action type based on available info
    if 'title' in element_info and element_info['title']:
        action_data["element_title"] = element_info['title']
    
    # Check for clipboard operations
    if command_key_pressed:
        if button == mouse.Button.left:
            # Check for common keyboard shortcuts
            if 'v' in modifiers:  # Cmd+V (Paste)
                # Get current clipboard content
                clipboard_content = get_clipboard_content()
                if clipboard_content and clipboard_content != last_clipboard_content:
                    action_data["action"] = "paste"
                    action_data["text"] = clipboard_content
                    last_clipboard_content = clipboard_content
            elif 'c' in modifiers:  # Cmd+C (Copy)
                action_data["action"] = "copy"
                # We'll update last_clipboard_content after a short delay
                threading.Timer(0.5, lambda: setattr(globals(), 'last_clipboard_content', get_clipboard_content())).start()
            elif 'x' in modifiers:  # Cmd+X (Cut)
                action_data["action"] = "cut"
                # We'll update last_clipboard_content after a short delay
                threading.Timer(0.5, lambda: setattr(globals(), 'last_clipboard_content', get_clipboard_content())).start()
    
    # Add to actions list
    actions.append(action_data)

def on_key_press(key):
    """Callback function for keyboard press events with semantic information"""
    global recording, actions, current_text_field, current_text_buffer
    global command_key_pressed, shift_key_pressed, control_key_pressed, option_key_pressed
    global active_app, active_window_title
    
    if not recording:
        return
    
    # Track modifier keys
    if key == keyboard.Key.cmd:
        command_key_pressed = True
    elif key == keyboard.Key.shift:
        shift_key_pressed = True
    elif key == keyboard.Key.ctrl:
        control_key_pressed = True
    elif key == keyboard.Key.alt:
        option_key_pressed = True
    
    # Get current modifiers
    modifiers = []
    if command_key_pressed:
        modifiers.append("command")
    if shift_key_pressed:
        modifiers.append("shift")
    if control_key_pressed:
        modifiers.append("control")
    if option_key_pressed:
        modifiers.append("option")
    
    # Handle special keys
    if hasattr(key, 'char') and key.char:
        # Regular character input - buffer it for text fields
        if current_text_field:
            current_text_buffer += key.char
        elif modifiers:  # If modifiers are pressed, record as keyboard shortcut
            shortcut_action = {
                "timestamp": time.time(),
                "action": "keyboard_shortcut",
                "key": key.char,
                "modifiers": modifiers,
                "application": active_app,
                "window_title": active_window_title
            }
            
            # Try to determine common shortcut actions
            shortcut_desc = "+".join(modifiers + [key.char])
            if command_key_pressed and key.char == 'c':
                shortcut_action["shortcut_action"] = "copy"
            elif command_key_pressed and key.char == 'v':
                shortcut_action["shortcut_action"] = "paste"
                # Get clipboard content
                clipboard_content = get_clipboard_content()
                if clipboard_content:
                    shortcut_action["text"] = clipboard_content
            elif command_key_pressed and key.char == 'x':
                shortcut_action["shortcut_action"] = "cut"
            elif command_key_pressed and key.char == 'z':
                shortcut_action["shortcut_action"] = "undo"
            elif command_key_pressed and shift_key_pressed and key.char == 'z':
                shortcut_action["shortcut_action"] = "redo"
            elif command_key_pressed and key.char == 'a':
                shortcut_action["shortcut_action"] = "select_all"
            elif command_key_pressed and key.char == 's':
                shortcut_action["shortcut_action"] = "save"
            elif command_key_pressed and key.char == 'p':
                shortcut_action["shortcut_action"] = "print"
            elif command_key_pressed and key.char == 'f':
                shortcut_action["shortcut_action"] = "find"
            
            actions.append(shortcut_action)
    elif key in SPECIAL_KEYS:
        key_name = SPECIAL_KEYS[key]
        
        # Handle special keys with context
        if key == keyboard.Key.enter:
            # Enter key - submit text or record as action
            if current_text_field and current_text_buffer:
                actions.append({
                    "timestamp": time.time(),
                    "action": "text_input",
                    "element": current_text_field,
                    "text": current_text_buffer,
                    "application": active_app,
                    "window_title": active_window_title,
                    "submit_method": "enter"
                })
                current_text_buffer = ""
                current_text_field = None
            else:
                actions.append({
                    "timestamp": time.time(),
                    "action": "key_press",
                    "key": key_name,
                    "modifiers": modifiers if modifiers else None,
                    "application": active_app,
                    "window_title": active_window_title
                })
        elif key == keyboard.Key.tab:
            # Tab key - might indicate field navigation
            if current_text_field and current_text_buffer:
                actions.append({
                    "timestamp": time.time(),
                    "action": "text_input",
                    "element": current_text_field,
                    "text": current_text_buffer,
                    "application": active_app,
                    "window_title": active_window_title,
                    "submit_method": "tab"
                })
                current_text_buffer = ""
                current_text_field = None
            
            actions.append({
                "timestamp": time.time(),
                "action": "key_press",
                "key": key_name,
                "modifiers": modifiers if modifiers else None,
                "application": active_app,
                "window_title": active_window_title
            })
        elif key == keyboard.Key.esc:
            # Escape key - might cancel current operation
            if current_text_field:
                current_text_buffer = ""
                current_text_field = None
            
            actions.append({
                "timestamp": time.time(),
                "action": "key_press",
                "key": key_name,
                "modifiers": modifiers if modifiers else None,
                "application": active_app,
                "window_title": active_window_title
            })
        elif key == keyboard.Key.space:
            # Space key - add space to text buffer or record as action
            if current_text_field:
                current_text_buffer += " "
            else:
                actions.append({
                    "timestamp": time.time(),
                    "action": "key_press",
                    "key": key_name,
                    "modifiers": modifiers if modifiers else None,
                    "application": active_app,
                    "window_title": active_window_title
                })
        else:
            # Other special keys
            actions.append({
                "timestamp": time.time(),
                "action": "key_press",
                "key": key_name,
                "modifiers": modifiers if modifiers else None,
                "application": active_app,
                "window_title": active_window_title
            })
    else:
        # Unknown key
        key_name = str(key).replace('Key.', '')
        actions.append({
            "timestamp": time.time(),
            "action": "key_press",
            "key": key_name,
            "modifiers": modifiers if modifiers else None,
            "application": active_app,
            "window_title": active_window_title
        })

def on_key_release(key):
    """Callback function for keyboard release events"""
    global command_key_pressed, shift_key_pressed, control_key_pressed, option_key_pressed
    
    # Track modifier keys
    if key == keyboard.Key.cmd:
        command_key_pressed = False
    elif key == keyboard.Key.shift:
        shift_key_pressed = False
    elif key == keyboard.Key.ctrl:
        control_key_pressed = False
    elif key == keyboard.Key.alt:
        option_key_pressed = False

def update_window_info_periodically():
    """Periodically update window information while recording"""
    global recording, active_app, active_window_title
    
    if not recording:
        return
    
    # Update window info
    update_active_window_info()
    
    # Schedule next update in 1 second if still recording
    if recording:
        threading.Timer(1.0, update_window_info_periodically).start()

def save_actions_to_json(out_dir):
    """Save recorded semantic actions to JSON file"""
    global actions, current_text_field, current_text_buffer, active_app, active_window_title
    
    # Flush any pending text input
    if current_text_field and current_text_buffer:
        actions.append({
            "timestamp": time.time(),
            "action": "text_input",
            "element": current_text_field,
            "text": current_text_buffer,
            "application": active_app,
            "window_title": active_window_title
        })
    
    # Add session metadata
    session_info = {
        "timestamp": time.time(),
        "action": "session_info",
        "session_duration": time.time() - actions[0]["timestamp"] if actions else 0,
        "action_count": len(actions),
        "applications": list(set(action.get("application") for action in actions if "application" in action))
    }
    actions.append(session_info)
    
    # Save actions
    actions_file = out_dir / "semantic_actions.json"
    with open(actions_file, 'w') as f:
        json.dump(actions, f, indent=2)
    
    c.print(f"[bold green]Semantic actions saved to {actions_file}[/]")
    
    # Also save a more processed workflow description
    try:
        workflow = generate_workflow_description(actions)
        workflow_file = out_dir / "workflow.json"
        with open(workflow_file, 'w') as f:
            json.dump(workflow, f, indent=2)
        c.print(f"[bold green]Workflow description saved to {workflow_file}[/]")
    except Exception as e:
        c.print(f"[bold yellow]Could not generate workflow description: {e}[/]")

def generate_workflow_description(actions):
    """Generate a higher-level workflow description from the recorded actions"""
    workflow = {
        "steps": [],
        "applications": {}
    }
    
    current_app = None
    text_inputs = {}
    
    for action in actions:
        if action["action"] == "session_info":
            continue
            
        # Track application usage
        app = action.get("application")
        if app and app != "unknown":
            if app != current_app:
                # Application switch
                workflow["steps"].append({
                    "type": "application_switch",
                    "application": app,
                    "timestamp": action["timestamp"]
                })
                current_app = app
            
            # Update application stats
            if app not in workflow["applications"]:
                workflow["applications"][app] = {
                    "action_count": 0,
                    "windows": set()
                }
            workflow["applications"][app]["action_count"] += 1
            
            # Track window titles
            window_title = action.get("window_title")
            if window_title:
                workflow["applications"][app]["windows"].add(window_title)
        
        # Process by action type
        if action["action"] == "text_input":
            workflow["steps"].append({
                "type": "text_input",
                "application": app,
                "window": action.get("window_title"),
                "text": action["text"],
                "timestamp": action["timestamp"]
            })
        elif action["action"] == "click":
            workflow["steps"].append({
                "type": "click",
                "application": app,
                "window": action.get("window_title"),
                "coordinates": {"x": action["x"], "y": action["y"]},
                "element_title": action.get("element_title"),
                "timestamp": action["timestamp"]
            })
        elif action["action"] == "keyboard_shortcut":
            workflow["steps"].append({
                "type": "shortcut",
                "application": app,
                "shortcut": "+".join(action.get("modifiers", []) + [action.get("key", "")]),
                "action": action.get("shortcut_action"),
                "timestamp": action["timestamp"]
            })
        elif action["action"] in ["copy", "paste", "cut"]:
            workflow["steps"].append({
                "type": action["action"],
                "application": app,
                "text": action.get("text"),
                "timestamp": action["timestamp"]
            })
    
    # Convert sets to lists for JSON serialization
    for app in workflow["applications"]:
        workflow["applications"][app]["windows"] = list(workflow["applications"][app]["windows"])
    
    return workflow

def start_recording():
    global recording, actions, active_app, active_window_title, mouse_listener, keyboard_listener, recording_proc, out_dir
    
    # Create a timestamped subfolder for this recording session
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_dir = base_dir / f"session_{ts}"
    out_dir.mkdir(exist_ok=True)
    
    # Initialize actions list and global tracking variables
    actions = []
    active_app = None
    active_window_title = None
    
    # Set up listeners for mouse and keyboard events
    mouse_listener = mouse.Listener(
        on_click=on_mouse_click
    )
    keyboard_listener = keyboard.Listener(
        on_press=on_key_press,
        on_release=on_key_release
    )
    
    # Get screen dimensions
    screen_size = CGDisplayBounds(CGMainDisplayID())
    center_x = screen_size.size.width / 2
    center_y = screen_size.size.height / 2
    
    # Test if we can get window information
    c.print("[bold yellow]Testing window information access...[/]")
    window_info = get_window_at_position(center_x, center_y)
    if window_info:
        c.print(f"[bold green]Successfully detected window: {window_info.get('application', 'Unknown')}[/]")
    else:
        c.print("[bold yellow]Could not detect window at screen center - will use basic recording[/]")
    
    # Get initial active application and window
    app_info = get_active_application_info()
    if app_info:
        active_app = app_info.get('application')
        c.print(f"[bold green]Active application: {active_app}[/]")
    
    window_info = update_active_window_info()
    if window_info:
        active_window_title = window_info.get('title')
        c.print(f"[bold green]Active window: {active_window_title}[/]")
    
    # Start listeners
    mouse_listener.start()
    keyboard_listener.start()
    
    # Start recording input events
    recording = True
    
    # Start periodic window info updates
    update_window_info_periodically()
    
    # Record session start
    actions.append({
        "timestamp": time.time(),
        "action": "session_start",
        "application": active_app,
        "window_title": active_window_title
    })
    
    # Audio test before recording
    c.print("[bold yellow]Testing audio devices before recording...[/]")
    
    # Start screen recording
    cmd, video_file = ffmpeg_cmd(out_dir)
    c.print(f"[bold green]Starting FFmpeg:[/]\n{cmd}\nPress [bold]Ctrl-C[/] to stop.")
    
    # shell=True for brevity; use list form if you prefer
    recording_proc = subprocess.Popen(cmd, shell=True)

    try:
        recording_proc.wait()
    except KeyboardInterrupt:
        stop_recording()

def stop_recording():
    """Stop the ongoing recording and save results"""
    global recording, actions, active_app, active_window_title, out_dir
    global mouse_listener, keyboard_listener, recording_proc

    c.print("\n[bold yellow]Stopping...[/]")
    recording_proc.send_signal(signal.SIGINT)
    recording_proc.wait()

    # Stop recording input events
    recording = False
    
    # Record session end
    actions.append({
        "timestamp": time.time(),
        "action": "session_end",
        "application": active_app,
        "window_title": active_window_title
    })
    
    # Stop listeners
    mouse_listener.stop()
    keyboard_listener.stop()
    
    # Save actions to JSON file
    save_actions_to_json(out_dir)
    
    c.print(f"[bold green]Recording session saved to {out_dir.resolve()}[/]")
    return out_dir

if __name__ == "__main__":
    start_recording()
