from computer import Computer
import asyncio
from typing import Optional, Dict, Any, List, Tuple

class VMController:
    def __init__(self, os: str = "macos", display: str = "1024x768", memory: str = "8GB", cpu: str = "4"):
        self.computer = Computer(os=os, display=display, memory=memory, cpu=cpu)

    async def run(self):
        await self.computer.run()

    async def stop(self):
        await self.computer.stop()

    async def screenshot(self) -> bytes:
        return await self.computer.interface.screenshot()

    async def cursor_position(self) -> dict[str, int]:
        return await self.computer.interface.get_cursor_position()

    async def move_cursor(self, x: int, y: int) -> None:
        await self.computer.interface.move_cursor(x, y)
    
    async def left_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        await self.computer.interface.left_click(x, y)

    async def right_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        await self.computer.interface.right_click(x, y)

    async def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        await self.computer.interface.double_click(x, y)

    async def drag_to(self, x: int, y: int, button: str = "left", duration: float = 0.5) -> None:
        await self.computer.interface.drag_to(x, y, button, duration)

    async def type_text(self, text: str) -> None:
        await self.computer.interface.type_text(text)

    async def press(self, key: "KeyType") -> None:
        await self.computer.interface.press(key)

    async def press_key(self, key: "KeyType") -> None:
        await self.computer.interface.press_key(key)

    async def hotkey(self, *keys) -> None:
        await self.computer.interface.hotkey(*keys)

    async def scroll_down(self, clicks: int = 1) -> None:
        await self.computer.interface.scroll_down(clicks)

    async def scroll_up(self, clicks: int = 1) -> None:
        await self.computer.interface.scroll_up(clicks)
        
    # Additional methods from MacOSComputerInterface
    
    # Screen Actions
    async def get_screen_size(self) -> Dict[str, int]:
        """Get the screen size."""
        return await self.computer.interface.get_screen_size()
    
    # Clipboard Actions
    async def copy_to_clipboard(self) -> str:
        """Copy the current selection to clipboard and return the content."""
        return await self.computer.interface.copy_to_clipboard()

    async def set_clipboard(self, text: str) -> None:
        """Set the clipboard content."""
        await self.computer.interface.set_clipboard(text)

    # File System Actions
    async def file_exists(self, path: str) -> bool:
        """Check if a file exists."""
        return await self.computer.interface.file_exists(path)

    async def directory_exists(self, path: str) -> bool:
        """Check if a directory exists."""
        return await self.computer.interface.directory_exists(path)

    async def run_command(self, command: str) -> Tuple[str, str]:
        """Run a shell command and return stdout and stderr."""
        return await self.computer.interface.run_command(command)

    # Accessibility Actions
    async def get_accessibility_tree(self) -> Dict[str, Any]:
        """Get the accessibility tree of the current screen."""
        return await self.computer.interface.get_accessibility_tree()

    async def get_active_window_bounds(self) -> Dict[str, int]:
        """Get the bounds of the currently active window."""
        return await self.computer.interface.get_active_window_bounds()

    # Coordinate Conversion
    async def to_screen_coordinates(self, x: float, y: float) -> Tuple[float, float]:
        """Convert screenshot coordinates to screen coordinates."""
        return await self.computer.interface.to_screen_coordinates(x, y)

    async def to_screenshot_coordinates(self, x: float, y: float) -> Tuple[float, float]:
        """Convert screen coordinates to screenshot coordinates."""
        return await self.computer.interface.to_screenshot_coordinates(x, y)


# async def main():
#     print("Creating computer instance")
#     computer = Computer(os="macos", display="1024x768", memory="8GB", cpu="4")
#     try:
#         print("Starting computer")
#         await computer.run()
        
#         print("Taking screenshot")
#         screenshot = await computer.interface.screenshot()
#         print("Saving screenshot to file")
#         with open("screenshot.png", "wb") as f:
#             f.write(screenshot)
        
#         print("Moving cursor to position (100, 100)")
#         await computer.interface.move_cursor(100, 100)
#         print("Performing left click")
#         await computer.interface.left_click()
#         print("Performing right click at position (300, 300)")
#         await computer.interface.right_click(300, 300)
#         print("Performing double click at position (400, 400)")
#         await computer.interface.double_click(400, 400)

#         print("Typing text: 'Hello, World!'")
#         await computer.interface.type_text("Hello, World!")
#         print("Pressing enter key")
#         await computer.interface.press_key("enter")

#         print("Setting clipboard content")
#         await computer.interface.set_clipboard("Test clipboard")
#         print("Copying content to clipboard")
#         content = await computer.interface.copy_to_clipboard()
#         print(f"Clipboard content: {content}")
#     finally:
#         print("Stopping computer")
#         # await computer.stop()

# if __name__ == "__main__":
#     print("Starting main function")
#     asyncio.run(main())
