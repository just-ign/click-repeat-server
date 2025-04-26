"""
Agentic sampling loop that calls the Anthropic API and local implementation of anthropic-defined computer use tools.
"""

import platform
from collections.abc import Callable, Awaitable
from datetime import datetime
from enum import StrEnum
from typing import Any, cast
import asyncio

import httpx
from anthropic import (
    Anthropic,
    AnthropicBedrock,
    AnthropicVertex,
    APIError,
    APIResponseValidationError,
    APIStatusError,
)
from anthropic.types.beta import (
    BetaCacheControlEphemeralParam,
    BetaContentBlockParam,
    BetaImageBlockParam,
    BetaMessage,
    BetaMessageParam,
    BetaTextBlock,
    BetaTextBlockParam,
    BetaToolResultBlockParam,
    BetaToolUseBlockParam,
)

from tools import (
    TOOL_GROUPS_BY_VERSION,
    ToolCollection,
    ToolResult,
    ToolVersion,
)

PROMPT_CACHING_BETA_FLAG = "prompt-caching-2024-07-31"


class APIProvider(StrEnum):
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    VERTEX = "vertex"


# This system prompt is optimized for the Docker environment in this repository and
# specific tool combinations enabled.
# We encourage modifying this system prompt to ensure the model has context for the
# environment it is running in, and to provide any additional information that may be
# helpful for the task at hand.
SYSTEM_PROMPT = f"""<SYSTEM_CAPABILITY>
* You are utilizing a macOS environment using {platform.machine()} architecture with internet access.
* You can feel free to install macOS applications with your bash tool. Use curl to download files and brew to install packages.
* To open Safari or other macOS applications, you can use the open command. For example, "open -a Safari".
* Using bash tool you can start GUI applications. GUI apps run with bash tool will appear on the desktop, but they may take some time to appear. Take a screenshot to confirm it did.
* Screenshots will be captured using the native macOS 'screencapture' utility, providing clear images of the screen.
* Mouse and keyboard interactions are handled via AppleScript on macOS, giving reliable control of the GUI.
* When using your bash tool with commands that are expected to output very large quantities of text, redirect into a tmp file and use str_replace_editor or `grep -n -B <lines before> -A <lines after> <query> <filename>` to confirm output.
* When viewing a page it can be helpful to zoom out so that you can see everything on the page. Either that, or make sure you scroll down to see everything before deciding something isn't available.
* When using your computer function calls, they take a while to run and send back to you. Where possible/feasible, try to chain multiple of these calls all into one function calls request.
* The current date is {datetime.today().strftime('%A, %B %-d, %Y')}.

<MAC_SHORTCUTS>
* Spotlight Search: Command + Space - Use to quickly find and open applications, documents, and other items, always clear your search if there is a previous search before using this. Do not open the weblink, just search for things on the current machine.
* App Switcher: Command + Tab - Switch between open applications
* Take Screenshot: Command + Shift + 3 (full screen) or Command + Shift + 4 (selection)
* Copy: Command + C
* Paste: Command + V
* Cut: Command + X
* Select All: Command + A
* Save: Command + S
* Print: Command + P
* Quit Application: Command + Q
* New Tab: Command + T
* Close Tab/Window: Command + W
* Force Quit: Option + Command + Esc
* Mission Control: Control + Up Arrow - View all open windows
* Show Desktop: F11 or Command + F3 - Hide all windows and show desktop
* Show Application Windows: Control + Down Arrow - Show all windows for the current application
* Quick Look: Space (when a file is selected in Finder) - Preview a file without opening it
* Finder Search: Command + F - Search for files in Finder
* Go to Folder: Command + Shift + G - Open a specific folder path in Finder
* Open Preferences: Command + , (comma) - Open preferences for the current application
</MAC_SHORTCUTS>
</SYSTEM_CAPABILITY>

<IMPORTANT>
Dont install anything new and dont delete any files.
</IMPORTANT>
"""

# """
# <IMPORTANT>
# * If the item you are looking at is a pdf, if after taking a single screenshot of the pdf it seems that you want to read the entire document instead of trying to continue to read the pdf from your screenshots + navigation, determine the URL, use curl to download the pdf, install and use pdftotext to convert it to a text file, and then read that text file directly with your StrReplaceEditTool.
# * For installing packages, macOS uses Homebrew. If it's not installed, you can install it with `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`.
# * You can launch applications using Spotlight by pressing Command + Space, then typing the application name.
# * To navigate between spaces/desktops, use Control + Left/Right arrows.
# </IMPORTANT>"""

computer_use_tool_description = """
 Use a mouse and keyboard to interact with a computer, and take screenshots.
 * This is an interface to a desktop GUI. You do not have access to a terminal or applications menu. You must click on desktop icons to start applications.
 * Some applications may take time to start or process actions, so you may need to wait and take successive screenshots to see the results of your actions. E.g. if you click on Firefox and a window doesn't open, try taking another screenshot.
 * The screen's resolution is 1024x768.
 * The display number is 1
 * Whenever you intend to move the cursor to click on an element like an icon, you should consult a screenshot to determine the coordinates of the element before moving the cursor.
 * If you tried clicking on a program or link but it failed to load, even after waiting, try adjusting your cursor position so that the tip of the cursor visually falls on the element that you want to click.
 * Make sure to click any buttons, links, icons, etc with the cursor tip in the center of the element. Don't click boxes on their edges unless asked.
"""

computer_use_tool_schema = {
   "properties": {
       "action": {
           "description": "The action to perform. The available actions are:\n"
           "* `key`: Press a key or key-combination on the keyboard.\n"
           "  - This supports xdotool's `key` syntax.\n"
           '  - Examples: "a", "Return", "alt+Tab", "ctrl+s", "Up", "KP_0" (for the numpad 0 key).\n'
           "* `hold_key`: Hold down a key or multiple keys for a specified duration (in seconds). Supports the same syntax as `key`.\n"
           "* `type`: Type a string of text on the keyboard.\n"
           "* `cursor_position`: Get the current (x, y) pixel coordinate of the cursor on the screen.\n"
           "* `mouse_move`: Move the cursor to a specified (x, y) pixel coordinate on the screen.\n"
           "* `left_mouse_down`: Press the left mouse button.\n"
           "* `left_mouse_up`: Release the left mouse button.\n"
           "* `left_click`: Click the left mouse button at the specified (x, y) pixel coordinate on the screen. You can also include a key combination to hold down while clicking using the `text` parameter.\n"
           "* `left_click_drag`: Click and drag the cursor from `start_coordinate` to a specified (x, y) pixel coordinate on the screen.\n"
           "* `right_click`: Click the right mouse button at the specified (x, y) pixel coordinate on the screen.\n"
           "* `middle_click`: Click the middle mouse button at the specified (x, y) pixel coordinate on the screen.\n"
           "* `double_click`: Double-click the left mouse button at the specified (x, y) pixel coordinate on the screen.\n"
           "* `triple_click`: Triple-click the left mouse button at the specified (x, y) pixel coordinate on the screen.\n"
           "* `scroll`: Scroll the screen in a specified direction by a specified amount of clicks of the scroll wheel, at the specified (x, y) pixel coordinate. DO NOT use PageUp/PageDown to scroll.\n"
           "* `wait`: Wait for a specified duration (in seconds).\n"
           "* `screenshot`: Take a screenshot of the screen.",
           "enum": [
               "key",
               "hold_key",
               "type",
               "cursor_position",
               "mouse_move",
               "left_mouse_down",
               "left_mouse_up",
               "left_click",
               "left_click_drag",
               "right_click",
               "middle_click",
               "double_click",
               "triple_click",
               "scroll",
               "wait",
               "screenshot",
               "run_command"
           ],
           "type": "string",
       },
       "coordinate": {
           "description": "(x, y): The x (pixels from the left edge) and y (pixels from the top edge) coordinates to move the mouse to. Required only by `action=mouse_move` and `action=left_click_drag`.",
           "type": "array",
       },
       "duration": {
           "description": "The duration to hold the key down for. Required only by `action=hold_key` and `action=wait`.",
           "type": "integer",
       },
       "scroll_amount": {
           "description": "The number of 'clicks' to scroll. Required only by `action=scroll`.",
           "type": "integer",
       },
       "scroll_direction": {
           "description": "The direction to scroll the screen. Required only by `action=scroll`.",
           "enum": ["up", "down", "left", "right"],
           "type": "string",
       },
       "start_coordinate": {
           "description": "(x, y): The x (pixels from the left edge) and y (pixels from the top edge) coordinates to start the drag from. Required only by `action=left_click_drag`.",
           "type": "array",
       },
       "text": {
           "description": "Required only by `action=type`, `action=key`, `action=hold_key` and `action=run_command`. Can also be used by click or scroll actions to hold down keys while clicking or scrolling.",
           "type": "string",
       },
   },
   "required": ["action"],
   "type": "object",
}


async def sampling_loop(
    *,
    model: str,
    provider: APIProvider,
    system_prompt_suffix: str,
    messages: list[BetaMessageParam],
    output_callback: Callable[[BetaContentBlockParam], Any],
    tool_output_callback: Callable[[ToolResult, str], Any],
    api_response_callback: Callable[
        [httpx.Request, httpx.Response | object | None, Exception | None], None
    ],
    api_key: str,
    only_n_most_recent_images: int | None = None,
    max_tokens: int = 4096,
    tool_version: ToolVersion,
    thinking_budget: int | None = None,
    token_efficient_tools_beta: bool = False,
    custom_tool_run: Callable[[ToolCollection, str, dict[str, Any], str], Awaitable[ToolResult]] | None = None,
):
    """
    Agentic sampling loop for the assistant/tool interaction of computer use.
    """
    tool_group = TOOL_GROUPS_BY_VERSION[tool_version]
    tool_collection = ToolCollection(*(ToolCls() for ToolCls in tool_group.tools))
    system = BetaTextBlockParam(
        type="text",
        text=f"{SYSTEM_PROMPT}{' ' + system_prompt_suffix if system_prompt_suffix else ''}",
    )

    while True:
        enable_prompt_caching = False
        betas = [tool_group.beta_flag] if tool_group.beta_flag else []
        if token_efficient_tools_beta:
            betas.append("token-efficient-tools-2025-02-19")
        image_truncation_threshold = only_n_most_recent_images or 0
        if provider == APIProvider.ANTHROPIC:
            client = Anthropic(api_key=api_key, max_retries=4)
            enable_prompt_caching = True
        elif provider == APIProvider.VERTEX:
            client = AnthropicVertex()
        elif provider == APIProvider.BEDROCK:
            client = AnthropicBedrock()

        if enable_prompt_caching:
            betas.append(PROMPT_CACHING_BETA_FLAG)
            _inject_prompt_caching(messages)
            # Because cached reads are 10% of the price, we don't think it's
            # ever sensible to break the cache by truncating images
            only_n_most_recent_images = 0
            # Use type ignore to bypass TypedDict check until SDK types are updated
            system["cache_control"] = {"type": "ephemeral"}  # type: ignore

        if only_n_most_recent_images:
            _maybe_filter_to_n_most_recent_images(
                messages,
                only_n_most_recent_images,
                min_removal_threshold=image_truncation_threshold,
            )
        extra_body = {}
        if thinking_budget:
            # Ensure we only send the required fields for thinking
            extra_body = {
                "thinking": {"type": "enabled", "budget_tokens": thinking_budget}
            }

        # Call the API
        # we use raw_response to provide debug information to streamlit. Your
        # implementation may be able call the SDK directly with:
        # `response = client.messages.create(...)` instead.
        try:
            # print(tool_collection.to_params())
            # Claude computer use tool direct Anthropic tool
            # tools = [{'name': 'computer', 'type': 'computer_20250124', 'display_width_px': 1366, 'display_height_px': 768, 'display_number': None}, {'name': 'str_replace_editor', 'type': 'text_editor_20250124'}, {'type': 'bash_20250124', 'name': 'bash'}]
            # Custom claude computer use tool
            tools=[
                # {
                #   "type": "computer_20250124",
                #   "name": "computer",
                #   "display_width_px": 1024,
                #   "display_height_px": 768,
                #   "display_number": 1,
                # },
                # {
                # "type": "text_editor_20250124",
                # "name": "str_replace_editor"
                # },
                # {
                # "type": "bash_20250124",
                # "name": "bash"
                # },
                {
                "name": "computer",
                "description": computer_use_tool_description,
                "input_schema": computer_use_tool_schema,
                },
            ]
            raw_response = client.beta.messages.with_raw_response.create(
                max_tokens=max_tokens,
                messages=messages,
                model=model,
                system=[system],
                tools=tools,
                betas=betas,
                extra_body=extra_body,
            )
        except (APIStatusError, APIResponseValidationError) as e:
            api_response_callback(e.request, e.response, e)
            return messages
        except APIError as e:
            api_response_callback(e.request, e.body, e)
            return messages

        api_response_callback(
            raw_response.http_response.request, raw_response.http_response, None
        )

        response = raw_response.parse()

        response_params = _response_to_params(response)
        messages.append(
            {
                "role": "assistant",
                "content": response_params,
            }
        )

        tool_result_content: list[BetaToolResultBlockParam] = []
        for content_block in response_params:
            result = output_callback(content_block)
            if asyncio.iscoroutine(result):
                await result
            if content_block["type"] == "tool_use":
                # Use custom tool run function if provided, otherwise use the default
                if custom_tool_run is not None:
                    result = await custom_tool_run(
                        tool_collection,
                        content_block["name"],
                        cast(dict[str, Any], content_block["input"]),
                        content_block["id"],
                    )
                else:
                    result = await tool_collection.run(
                        name=content_block["name"],
                        tool_input=cast(dict[str, Any], content_block["input"]),
                    )
                tool_result_content.append(
                    _make_api_tool_result(result, content_block["id"])
                )
                tool_result = tool_output_callback(result, content_block["id"])
                if asyncio.iscoroutine(tool_result):
                    await tool_result

        if not tool_result_content:
            return messages

        messages.append({"content": tool_result_content, "role": "user"})


def _maybe_filter_to_n_most_recent_images(
    messages: list[BetaMessageParam],
    images_to_keep: int,
    min_removal_threshold: int,
):
    """
    With the assumption that images are screenshots that are of diminishing value as
    the conversation progresses, remove all but the final `images_to_keep` tool_result
    images in place, with a chunk of min_removal_threshold to reduce the amount we
    break the implicit prompt cache.
    """
    if images_to_keep is None:
        return messages

    tool_result_blocks = cast(
        list[BetaToolResultBlockParam],
        [
            item
            for message in messages
            for item in (
                message["content"] if isinstance(message["content"], list) else []
            )
            if isinstance(item, dict) and item.get("type") == "tool_result"
        ],
    )

    total_images = sum(
        1
        for tool_result in tool_result_blocks
        for content in tool_result.get("content", [])
        if isinstance(content, dict) and content.get("type") == "image"
    )

    images_to_remove = total_images - images_to_keep
    # for better cache behavior, we want to remove in chunks
    images_to_remove -= images_to_remove % min_removal_threshold

    for tool_result in tool_result_blocks:
        if isinstance(tool_result.get("content"), list):
            new_content = []
            for content in tool_result.get("content", []):
                if isinstance(content, dict) and content.get("type") == "image":
                    if images_to_remove > 0:
                        images_to_remove -= 1
                        continue
                new_content.append(content)
            tool_result["content"] = new_content


def _response_to_params(
    response: BetaMessage,
) -> list[BetaContentBlockParam]:
    res: list[BetaContentBlockParam] = []
    for block in response.content:
        if isinstance(block, BetaTextBlock):
            if block.text:
                res.append(BetaTextBlockParam(type="text", text=block.text))
            elif getattr(block, "type", None) == "thinking":
                # Handle thinking blocks - include signature field
                thinking_block = {
                    "type": "thinking",
                    "thinking": getattr(block, "thinking", None),
                }
                if hasattr(block, "signature"):
                    thinking_block["signature"] = getattr(block, "signature", None)
                res.append(cast(BetaContentBlockParam, thinking_block))
        else:
            # Handle tool use blocks normally
            res.append(cast(BetaToolUseBlockParam, block.model_dump()))
    return res


def _inject_prompt_caching(
    messages: list[BetaMessageParam],
):
    """
    Set cache breakpoints for the 3 most recent turns
    one cache breakpoint is left for tools/system prompt, to be shared across sessions
    """

    breakpoints_remaining = 3
    for message in reversed(messages):
        if message["role"] == "user" and isinstance(
            content := message["content"], list
        ):
            if breakpoints_remaining:
                breakpoints_remaining -= 1
                # Use type ignore to bypass TypedDict check until SDK types are updated
                content[-1]["cache_control"] = BetaCacheControlEphemeralParam(  # type: ignore
                    {"type": "ephemeral"}
                )
            else:
                content[-1].pop("cache_control", None)
                # we'll only every have one extra turn per loop
                break


def _make_api_tool_result(
    result: ToolResult, tool_use_id: str
) -> BetaToolResultBlockParam:
    """Convert an agent ToolResult to an API ToolResultBlockParam."""
    tool_result_content: list[BetaTextBlockParam | BetaImageBlockParam] | str = []
    is_error = False
    if result.error:
        is_error = True
        tool_result_content = _maybe_prepend_system_tool_result(result, result.error)
    else:
        if result.output:
            tool_result_content.append(
                {
                    "type": "text",
                    "text": _maybe_prepend_system_tool_result(result, result.output),
                }
            )
        if result.base64_image:
            tool_result_content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": result.base64_image,
                    },
                }
            )
    return {
        "type": "tool_result",
        "content": tool_result_content,
        "tool_use_id": tool_use_id,
        "is_error": is_error,
    }


def _maybe_prepend_system_tool_result(result: ToolResult, result_text: str):
    if result.system:
        result_text = f"<system>{result.system}</system>\n{result_text}"
    return result_text
