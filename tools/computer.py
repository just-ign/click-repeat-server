import asyncio
import base64
import io
import os
import shlex
import shutil
import sys
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypedDict, cast, get_args
from uuid import uuid4

import pyautogui
from anthropic.types.beta import BetaToolComputerUse20241022Param, BetaToolUnionParam

from .base import BaseAnthropicTool, ToolError, ToolResult
from .run import run

from .vm_controller import VMController
import asyncio

vm_controller = VMController()

# Initialize the VM controller when the module is imported
async def _initialize_vm_controller():
    await vm_controller.run()

# Run the initialization in a non-blocking way
try:
    asyncio.run(_initialize_vm_controller())
    print("VM controller initialized successfully")
except Exception as e:
    print(f"Failed to initialize VM controller: {e}")

# Store screenshots in current working directory
OUTPUT_DIR = os.getcwd() + "/screenshots"

TYPING_DELAY_MS = 12
TYPING_GROUP_SIZE = 50

Action_20241022 = Literal[
    "key",
    "type",
    "mouse_move",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "double_click",
    "screenshot",
    "cursor_position",
    "run_command",
]

Action_20250124 = (
    Action_20241022
    | Literal[
        "left_mouse_down",
        "left_mouse_up",
        "scroll",
        "hold_key",
        "wait",
        "triple_click",
        "copy_to_clipboard",
    ]
)

ScrollDirection = Literal["up", "down", "left", "right"]


class Resolution(TypedDict):
    width: int
    height: int


# sizes above XGA/WXGA are not recommended (see README.md)
# scale down to one of these targets if ComputerTool._scaling_enabled is set
MAX_SCALING_TARGETS: dict[str, Resolution] = {
    "XGA": Resolution(width=1024, height=768),  # 4:3
    "WXGA": Resolution(width=1280, height=800),  # 16:10
    "FWXGA": Resolution(width=1366, height=768),  # ~16:9
}

CLICK_BUTTONS = {
    "left_click": 1,
    "right_click": 3,
    "middle_click": 2,
    "double_click": "--repeat 2 --delay 10 1",
    "triple_click": "--repeat 3 --delay 10 1",
}


class ScalingSource(StrEnum):
    COMPUTER = "computer"
    API = "api"


class ComputerToolOptions(TypedDict):
    display_height_px: int
    display_width_px: int
    display_number: int | None


def chunks(s: str, chunk_size: int) -> list[str]:
    return [s[i : i + chunk_size] for i in range(0, len(s), chunk_size)]


class BaseComputerTool:
    """
    A tool that allows the agent to interact with the screen, keyboard, and mouse of the current computer.
    The tool parameters are defined by Anthropic and are not editable.
    """

    name: Literal["computer"] = "computer"
    width: int
    height: int
    display_num: int | None

    _screenshot_delay = 1.0
    _scaling_enabled = True

    @property
    def options(self) -> ComputerToolOptions:
        width, height = self.scale_coordinates(
            ScalingSource.COMPUTER, self.width, self.height
        )
        return {
            "display_width_px": width,
            "display_height_px": height,
            "display_number": self.display_num,
        }

    def __init__(self):
        super().__init__()

        # Create output directory if it doesn't exist
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # Initialize PyAutoGUI settings
        pyautogui.FAILSAFE = False  # Disable fail-safe feature

        # Get screen size using PyAutoGUI
        try:
            screen_size = pyautogui.size()
            self.width = int(screen_size[0])
            self.height = int(screen_size[1])
        except Exception as e:
            print(f"Error getting screen size with PyAutoGUI: {str(e)}")
            # Fall back to environment variables if PyAutoGUI fails
            self.width = int(os.getenv("WIDTH") or 1024)
            self.height = int(os.getenv("HEIGHT") or 768)

        assert self.width and self.height, "Screen dimensions must be non-zero"
        
        # Get display number from environment if available
        if (display_num := os.getenv("DISPLAY_NUM")) is not None:
            self.display_num = int(display_num)
            self._display_prefix = f"DISPLAY=:{self.display_num} "
        else:
            self.display_num = None
            self._display_prefix = ""

        # Check if running on macOS
        self.is_macos = sys.platform == "darwin"
        if not self.is_macos:
            self.xdotool = f"{self._display_prefix}xdotool"

    async def __call__(
        self,
        *,
        action: Action_20241022,
        text: str | None = None,
        coordinate: tuple[int, int] | None = None,
        **kwargs,
    ):
        print(f"### Performing action: {action}{f', text: {text}' if text else ''}{f', coordinate: {coordinate}' if coordinate else ''}")

        if action == "run_command":
            await vm_controller.run_command(text)
            return await self.make_result(f"Command '{text}' run", take_screenshot=False)
        
        # PyAutoGUI implementation for all platforms
        if action in ("mouse_move", "left_click_drag"):
            if coordinate is None:
                raise ToolError(f"coordinate is required for {action}")
            if text is not None:
                raise ToolError(f"text is not accepted for {action}")

            # x, y = self.validate_and_get_coordinates(coordinate)
            x, y = coordinate
            x, y = await vm_controller.to_screen_coordinates(x, y)

            if action == "mouse_move":
                try:
                    # await vm_controller.move_cursor(x, y)
                    await vm_controller.move_cursor(x, y)
                    return await self.make_result(f"Mouse moved to {x}, {y}")
                except Exception as e:
                    raise ToolError(f"Failed to move mouse: {str(e)}")
            elif action == "left_click_drag":
                try:
                    # Get current position first
                    current_pos = await vm_controller.cursor_position()
                    # Click, drag, and release
                    await vm_controller.drag_to(x, y, button='left', duration=0.5)
                    return await self.make_result(f"Mouse dragged from {current_pos} to {x}, {y}")
                except Exception as e:
                    raise ToolError(f"Failed to drag mouse: {str(e)}")

        if action in ("key", "type"):
            if text is None:
                raise ToolError(f"text is required for {action}")
            if coordinate is not None:
                raise ToolError(f"coordinate is not accepted for {action}")
            if not isinstance(text, str):
                raise ToolError(output=f"{text} must be a string")

            if action == "key":
                try:
                    # Special case for Spotlight (Command+Space)
                    if text.lower() in ("command+space", "cmd+space") and self.is_macos:
                        try:
                            # Fallback to AppleScript if needed
                            applescript = '''
                            tell application "System Events"
                                keystroke space using command down
                                delay 0.1
                            end tell
                            '''
                            await run(f"osascript -e '{applescript}'")
                            return await self.make_result(f"Spotlight triggered via AppleScript")
                        except Exception as e:
                            raise ToolError(f"Failed to open Spotlight: {str(e)}")
                    
                    # Handle key combinations and modifiers
                    key_sequence = text.lower().replace("super", "command").split("+")
                    key_sequence = [key.strip() for key in key_sequence]
                    # Map 'cmd' to 'command' for MacOS
                    key_sequence = [
                        "command" if key == "cmd" else key for key in key_sequence
                    ]
                    await vm_controller.hotkey(*key_sequence)
                    return await self.make_result(f"Key combination '{text}' pressed")
                except Exception as e:
                    raise ToolError(f"Failed to press key: {str(e)}")
            elif action == "type":
                try:
                    results = []
                    for chunk in chunks(text, TYPING_GROUP_SIZE):
                        await vm_controller.type_text(chunk)
                        results.append(f"Typed chunk: {chunk}")
                    
                    return await self.make_result("".join(results))
                except Exception as e:
                    raise ToolError(f"Failed to type text: {str(e)}")

        if action in (
            "left_click",
            "right_click",
            "double_click",
            "middle_click",
            "screenshot",
            "cursor_position",
        ):
            if text is not None:
                raise ToolError(f"text is not accepted for {action}")

            if action == "screenshot":
                return await self.screenshot()
                
            elif action == "cursor_position":
                try:
                    position = await vm_controller.cursor_position()
                    x, y = position["x"], position["y"]
                    x, y = await vm_controller.to_screenshot_coordinates(x, y)
                    # api_x, api_y = self.scale_coordinates(ScalingSource.COMPUTER, x, y) #TODO Check if scaling is required
                    return await self.make_result(f"X={x},Y={y}")
                except Exception as e:
                    raise ToolError(f"Failed to get cursor position: {str(e)}")
                    
            else:  # Handle clicks
                # If coordinates are provided, move to that position first
                if coordinate is not None:
                    # x, y = self.validate_and_get_coordinates(coordinate)
                    x, y = coordinate
                    x, y = await vm_controller.to_screen_coordinates(x, y)
                    try:
                        await vm_controller.move_cursor(x, y)
                    except Exception as e:
                        raise ToolError(f"Failed to move mouse to {x}, {y}: {str(e)}")
                
                try:
                    if action == "left_click":
                        await vm_controller.left_click(x, y)
                        return await self.make_result("Left click performed")
                    elif action == "right_click":
                        await vm_controller.right_click(x, y)
                        return await self.make_result("Right click performed")
                    elif action == "double_click":
                        await vm_controller.double_click(x, y)
                        return await self.make_result("Double click performed")
                    elif action == "middle_click":
                        # Middle click not directly supported in VM interface
                        await vm_controller.left_click(x, y)
                        return await self.make_result("Middle click performed")
                except Exception as e:
                    raise ToolError(f"Failed to perform {action}: {str(e)}")

        raise ToolError(f"Invalid action: {action}")

    def validate_and_get_coordinates(self, coordinate: tuple[int, int] | None = None):
        """Validate coordinates and scale them as needed."""
        if not isinstance(coordinate, tuple) and not isinstance(coordinate, list):
            raise ToolError(f"{coordinate} must be a tuple or list of length 2")
        if len(coordinate) != 2:
            raise ToolError(f"{coordinate} must contain exactly 2 values")
        if not all(isinstance(i, int) and i >= 0 for i in coordinate):
            raise ToolError(f"{coordinate} must contain non-negative integers")

        return self.scale_coordinates(ScalingSource.API, coordinate[0], coordinate[1])

    async def make_result(self, output: str, take_screenshot: bool = True) -> ToolResult:
        """Helper to create a ToolResult with optional screenshot."""
        if take_screenshot:
            await asyncio.sleep(self._screenshot_delay)
            try:
                screenshot_result = await self.screenshot()
                return ToolResult(
                    output=output,
                    base64_image=screenshot_result.base64_image
                )
            except Exception as e:
                print(f"Screenshot error in make_result: {str(e)}")
                return ToolResult(output=output)
        return ToolResult(output=output)

    async def screenshot(self):
        """Take a screenshot of the current screen and return the base64 encoded image."""
        # Ensure the screenshots directory exists
        # output_dir = Path(OUTPUT_DIR)
        # output_dir.mkdir(parents=True, exist_ok=True)
        
        # # Create a unique filename for the screenshot
        # path = output_dir / f"screenshot_{uuid4().hex}.png"
        
        # print(f"Saving screenshot to: {path}")

        try:
            # # Use macOS native screencapture
            # screenshot_cmd = f"screencapture -x {path}"
            # result = await self.shell(screenshot_cmd, take_screenshot=False)
            
            # # Apply fixed scaling if needed
            # if self._scaling_enabled:
            #     target_dimension = MAX_SCALING_TARGETS["FWXGA"]  # Fixed to 1366x768
            #     # Use sips (macOS built-in image processing) to resize
            #     resize_cmd = f"sips -z {target_dimension['height']} {target_dimension['width']} {path}"
            #     await self.shell(resize_cmd, take_screenshot=False)
            
            # # Read the file and encode as base64
            # if not path.exists():
            #     raise ToolError(f"Screenshot file not found at {path}")
                
            # base64_data = base64.b64encode(path.read_bytes()).decode()

            # Get the screenshot as bytes from vm_controller
            screenshot_bytes = await vm_controller.screenshot()
            
            # Encode the bytes as base64 string
            base64_data = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            return ToolResult(
                output=f"Screenshot taken",
                base64_image=base64_data
            )
        except Exception as e:
            raise ToolError(f"Failed to take screenshot: {str(e)}")

    async def shell(self, command: str, take_screenshot=False) -> ToolResult:
        """Run a shell command and return the output, error, and optionally a screenshot."""
        _, stdout, stderr = await run(command)
        base64_image = None

        if take_screenshot:
            # delay to let things settle before taking a screenshot
            await asyncio.sleep(self._screenshot_delay)
            base64_image = (await self.screenshot()).base64_image
            

        return ToolResult(output=stdout, error=stderr, base64_image=base64_image)

    def scale_coordinates(self, source: ScalingSource, x: int, y: int):
        """Scale coordinates to a fixed target resolution."""
        if not self._scaling_enabled:
            return x, y
        
        # Use a fixed target resolution for consistent scaling
        target_dimension = MAX_SCALING_TARGETS["FWXGA"]  # Fixed to 1366x768
                
        # Calculate scaling factors
        x_scaling_factor = target_dimension["width"] / self.width
        y_scaling_factor = target_dimension["height"] / self.height
        
        if source == ScalingSource.API:
            if x > target_dimension["width"] or y > target_dimension["height"]:
                raise ToolError(f"Coordinates {x}, {y} are out of bounds")
            # scale up to real screen coordinates
            return round(x / x_scaling_factor), round(y / y_scaling_factor)
        
        # scale down from real screen to API coordinates
        return round(x * x_scaling_factor), round(y * y_scaling_factor)


class ComputerTool20241022(BaseComputerTool, BaseAnthropicTool):
    api_type: Literal["computer_20241022"] = "computer_20241022"

    def to_params(self) -> BetaToolComputerUse20241022Param:
        return {"name": self.name, "type": self.api_type, **self.options}


class ComputerTool20250124(BaseComputerTool, BaseAnthropicTool):
    api_type: Literal["computer_20250124"] = "computer_20250124"

    def to_params(self):
        return cast(
            BetaToolUnionParam,
            {"name": self.name, "type": self.api_type, **self.options},
        )

    async def __call__(
        self,
        *,
        action: Action_20250124,
        text: str | None = None,
        coordinate: tuple[int, int] | None = None,
        scroll_direction: ScrollDirection | None = None,
        scroll_amount: int | None = None,
        duration: int | float | None = None,
        key: str | None = None,
        **kwargs,
    ):
        # Handle new action types with PyAutoGUI
        if action in ("left_mouse_down", "left_mouse_up"):
            try:
                if action == "left_mouse_down":
                    await vm_controller.left_mouse_down()
                    return await self.make_result("Left mouse button pressed down")
                else:
                    await vm_controller.left_mouse_up()
                    return await self.make_result("Left mouse button released")
            except Exception as e:
                raise ToolError(f"Failed to perform {action}: {str(e)}")
                
        if action == "scroll":
            if scroll_direction is None or scroll_direction not in get_args(ScrollDirection):
                raise ToolError(f"scroll_direction must be one of: {get_args(ScrollDirection)}")
            if not isinstance(scroll_amount, int) or scroll_amount < 0:
                raise ToolError(f"scroll_amount must be a non-negative integer")
                
            # Move to coordinates if provided
            if coordinate is not None:
                x, y = self.validate_and_get_coordinates(coordinate)
                try:
                    await vm_controller.move_cursor(x, y)
                except Exception as e:
                    raise ToolError(f"Failed to move mouse to {x}, {y}: {str(e)}")
            
            try:
                # Convert scroll direction to appropriate PyAutoGUI values
                # Apply a multiplier to make scrolling more noticeable (especially on macOS)
                scroll_multiplier = 5  # Increase this value for more pronounced scrolling
                scroll_value = 0
                if scroll_direction == "up":
                    scroll_value = scroll_amount * scroll_multiplier
                elif scroll_direction == "down":
                    scroll_value = -scroll_amount * scroll_multiplier
                # elif scroll_direction == "left":
                #     # PyAutoGUI uses a different function for horizontal scrolling
                #     # await asyncio.to_thread(pyautogui.hscroll, -scroll_amount * scroll_multiplier)
                #     return await self.make_result(f"Scrolled left {scroll_amount} times")
                # elif scroll_direction == "right":
                #     # await asyncio.to_thread(pyautogui.hscroll, scroll_amount * scroll_multiplier)
                #     return await self.make_result(f"Scrolled right {scroll_amount} times")
                
                # Vertical scroll
                if scroll_direction in ("up", "down"):
                    # On macOS, use an alternative approach for more reliable scrolling
                    if self.is_macos:
                        try:
                        #     # Use vscroll method if available (newer PyAutoGUI versions)
                        #     if hasattr(pyautogui, 'vscroll'):
                        #         await asyncio.to_thread(pyautogui.vscroll, scroll_value)
                        #     else:
                        #         # Try multiple smaller scrolls for more reliability
                        #         for _ in range(abs(scroll_amount)):
                        #             increment = 25 if scroll_direction == "up" else -25
                        #             await asyncio.to_thread(pyautogui.scroll, increment * scroll_multiplier // 10)
                        #             await asyncio.sleep(0.05)  # Small delay between scrolls
                        # except Exception as e:
                        #     print(f"PyAutoGUI scrolling failed: {str(e)}. Trying AppleScript...")
                        #     # Fallback to AppleScript as a last resort
                        #     direction_str = "up" if scroll_direction == "up" else "down"
                        #     count = scroll_amount * 5  # Multiply for more visible effect
                        #     applescript = f'''
                        #     tell application "System Events"
                        #         repeat {count} times
                        #             key code {126 if direction_str == "up" else 125}  # 126=up, 125=down arrow keys
                        #             delay 0.05
                        #         end repeat
                        #     end tell
                        #     '''
                        #     await run(f"osascript -e '{applescript}'")
                            if scroll_direction == "up":
                                await vm_controller.scroll_up(scroll_amount)
                            else:
                                await vm_controller.scroll_down(scroll_amount)
                        except Exception as e:
                            raise ToolError(f"Failed to scroll: {str(e)}")
                    else:
                        # On other platforms, use regular scroll
                        # await asyncio.to_thread(pyautogui.scroll, scroll_value)
                        if scroll_direction == "up":
                            await vm_controller.scroll_up(scroll_amount)
                        else:
                            await vm_controller.scroll_down(scroll_amount)
                    
                    return await self.make_result(f"Scrolled {scroll_direction} {scroll_amount} times")
            except Exception as e:
                raise ToolError(f"Failed to scroll: {str(e)}")

        # if action in ("hold_key", "wait"): #TODO Move to VM controller
            # if duration is None or not isinstance(duration, (int, float)):
            #     raise ToolError(f"duration must be a number")
            # if duration < 0:
            #     raise ToolError(f"duration must be non-negative")
            # if duration > 100:
            #     raise ToolError(f"duration is too long (max 100)")

            # if action == "hold_key":
            #     if text is None:
            #         raise ToolError(f"text is required for {action}")
            #     try:
            #         await asyncio.to_thread(pyautogui.keyDown, text)
            #         await asyncio.sleep(duration)
            #         await asyncio.to_thread(pyautogui.keyUp, text)
            #         return await self.make_result(f"Held key '{text}' for {duration} seconds")
            #     except Exception as e:
            #         raise ToolError(f"Failed to hold key: {str(e)}")

            if action == "wait":
                await asyncio.sleep(duration)
                return await self.screenshot()

        if action == "triple_click":
            if coordinate is not None:
                x, y = self.validate_and_get_coordinates(coordinate)
                try:
                    await vm_controller.move_cursor(x, y)
                    # Triple click not directly supported in VM interface
                    await vm_controller.double_click()
                    return await self.make_result(f"Triple clicked at {x}, {y}")
                except Exception as e:
                    raise ToolError(f"Failed to triple click: {str(e)}")
            else:
                try:
                    # Triple click not directly supported in VM interface
                    await vm_controller.double_click()
                    return await self.make_result("Triple clicked at current position")
                except Exception as e:
                    raise ToolError(f"Failed to triple click: {str(e)}")
        
        if action == "copy_to_clipboard":
            try:
                content = await vm_controller.copy_to_clipboard()
                return await self.make_result(f"Copied to clipboard: {content}")
            except Exception as e:
                raise ToolError(f"Failed to copy to clipboard: {str(e)}")

        # For other actions, delegate to the parent implementation
        return await super().__call__(
            action=action, text=text, coordinate=coordinate, key=key, **kwargs
        )
