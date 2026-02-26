# agent_tools.py
# ADK Tool functions that the Gemini agent calls to interact with the browser.
# Each tool returns a structured string that the main WebSocket loop intercepts
# and maps to a real BrowserEngine action.

from __future__ import annotations
import json


# ──────────────────────────────────────────────────────────────────────────────
# Navigation & Interaction Tools
# ──────────────────────────────────────────────────────────────────────────────

def navigate_to_url(url: str) -> str:
    """
    Navigate the browser to a specific URL.
    Use this when you need to visit a new page or when redirected unexpectedly.

    Args:
        url: The full URL to navigate to (e.g. 'https://example.com/login').
    """
    return json.dumps({"action": "navigate", "url": url})


def click_element(x: int, y: int) -> str:
    """
    Click on a UI element at the specified pixel coordinates on the 1280x720 viewport.
    Estimate the center of the target element precisely.
    After calling this, you will receive a new screenshot showing the result.

    Args:
        x: Horizontal pixel coordinate (0 = left edge, 1280 = right edge).
        y: Vertical pixel coordinate (0 = top edge, 720 = bottom edge).
    """
    return json.dumps({"action": "click", "x": x, "y": y})


def type_into_field(text: str) -> str:
    """
    Type text into the currently focused input field or textarea.
    Always use click_element on the input field FIRST to focus it.

    Args:
        text: The text to type into the focused field.
    """
    return json.dumps({"action": "type", "text": text})


def press_keyboard_key(key: str) -> str:
    """
    Press a special keyboard key.
    Use this after filling a form field to submit it, or to dismiss popups.

    Args:
        key: The key to press. Examples: 'Enter', 'Tab', 'Escape', 'ArrowDown'.
    """
    return json.dumps({"action": "key", "key": key})


def scroll_page(direction: str, amount: int = 300) -> str:
    """
    Scroll the page to reveal more content.
    Use this when you need to see elements below or above the current view.

    Args:
        direction: Either 'down' or 'up'.
        amount: Pixels to scroll. Default is 300. Use 600 for large pages.
    """
    return json.dumps({"action": "scroll", "direction": direction, "amount": amount})


def hover_over_element(x: int, y: int) -> str:
    """
    Move the mouse cursor over an element to reveal tooltips, hover menus, or dropdown items.

    Args:
        x: Horizontal pixel coordinate.
        y: Vertical pixel coordinate.
    """
    return json.dumps({"action": "hover", "x": x, "y": y})


def go_back() -> str:
    """
    Navigate back to the previous page in browser history.
    Use this to recover from navigation errors or to test the back button behavior.
    """
    return json.dumps({"action": "back"})


# ──────────────────────────────────────────────────────────────────────────────
# QA / Reporting Tools
# ──────────────────────────────────────────────────────────────────────────────

def flag_visual_bug(
    description: str,
    severity: str,
    x: int = -1,
    y: int = -1,
) -> str:
    """
    Report a visual or UX bug found on the current page.
    Call this whenever you observe overlapping text, broken images, misaligned elements,
    inaccessible buttons, poor contrast, or any other UI defect.

    Args:
        description: A clear, concise description of the bug (1-2 sentences).
        severity: One of 'critical', 'high', 'medium', or 'low'.
                  critical = interaction-blocking, high = major UX issue,
                  medium = noticeable defect, low = cosmetic issue.
        x: Optional X coordinate of the bug's location on screen (-1 if not applicable).
        y: Optional Y coordinate of the bug's location on screen (-1 if not applicable).
    """
    return json.dumps({
        "action": "bug",
        "description": description,
        "severity": severity,
        "x": x,
        "y": y,
    })


def mark_test_complete(summary: str, bugs_found: int) -> str:
    """
    Call this ONLY when the testing objective has been fully completed.
    This ends the current test session.

    Args:
        summary: A brief summary of what was tested and the overall quality assessment.
        bugs_found: The total number of bugs flagged during this session.
    """
    return json.dumps({
        "action": "complete",
        "summary": summary,
        "bugs_found": bugs_found,
    })
