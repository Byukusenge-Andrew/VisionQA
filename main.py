# main.py
# Visual QA Sniper — FastAPI backend
# Drives the action-observation loop with ADK + Gemini + Playwright

from __future__ import annotations
import asyncio
import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ── Google GenAI SDK ──────────────────────────────────────────────────────────
import google.generativeai as genai

# ── Local modules ─────────────────────────────────────────────────────────────
from vision_engine import BrowserEngine
from session_manager import SessionManager

# ─────────────────────────────────────────────────────────────────────────────
# App + Gemini Setup
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Visual QA Sniper API", version="1.0.0")
session_mgr = SessionManager()

Path("static").mkdir(exist_ok=True)

API_KEY = os.environ.get("GOOGLE_API_KEY", "")
genai.configure(api_key=API_KEY)

SYSTEM_INSTRUCTION = """
You are **Visual QA Sniper**, an elite autonomous web UI testing agent.
You interact with web applications ENTIRELY through visual computer vision.
You are NOT allowed to inspect HTML, DOM, or source code.

## Your Core Workflow
1. OBSERVE: Study the screenshot carefully (viewport is exactly 1280×720 pixels).
2. PLAN: Decide the single next logical action toward the testing goal.
3. ACT: Call exactly ONE function and return. Do NOT narrate — just call the function.
4. ANALYZE: After each new screenshot, evaluate whether your action succeeded.
5. REPEAT until the goal is complete or you have explored all relevant paths.

## Rules
- Never ask the user for permission. Execute immediately.
- Aim for the precise CENTER of each button, link, or input field.
- After typing in a form field, press Enter OR click the submit button.
- Scroll to find content below the fold if needed.
- If you observe visual defects (overlapping text, broken images, misaligned elements,
  poor contrast, missing images, cut-off text) call flag_visual_bug IMMEDIATELY.
- When the test is fully complete, call mark_test_complete.

## Bug severity
- critical: Blocks core user task
- high: Major UX degradation
- medium: Noticeable defect
- low: Cosmetic only

## Coordinate system
(0,0) = top-left. (1280,720) = bottom-right. Aim for element centers.
"""


def build_model() -> genai.GenerativeModel:
    """Build a Gemini model with all QA tool definitions."""
    tools = genai.protos.Tool(
        function_declarations=[
            genai.protos.FunctionDeclaration(
                name="navigate_to_url",
                description="Navigate the browser to a specific URL.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={"url": genai.protos.Schema(type=genai.protos.Type.STRING,
                                description="Full URL including https://")},
                    required=["url"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="click_element",
                description="Click a UI element at the given pixel coordinates. Estimate the center of the target.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "x": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Horizontal coordinate (0-1280)"),
                        "y": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Vertical coordinate (0-720)"),
                    },
                    required=["x", "y"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="type_into_field",
                description="Type text into the currently focused input field. Click the field first.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={"text": genai.protos.Schema(type=genai.protos.Type.STRING, description="Text to type")},
                    required=["text"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="press_keyboard_key",
                description="Press a keyboard key such as Enter, Tab, Escape, ArrowDown.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={"key": genai.protos.Schema(type=genai.protos.Type.STRING, description="Key name, e.g. 'Enter'")},
                    required=["key"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="scroll_page",
                description="Scroll the page to reveal more content.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "direction": genai.protos.Schema(type=genai.protos.Type.STRING, description="'up' or 'down'"),
                        "amount": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Pixels to scroll, default 300"),
                    },
                    required=["direction"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="hover_over_element",
                description="Hover the mouse over a coordinate to reveal dropdowns or tooltips.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "x": genai.protos.Schema(type=genai.protos.Type.INTEGER),
                        "y": genai.protos.Schema(type=genai.protos.Type.INTEGER),
                    },
                    required=["x", "y"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="go_back",
                description="Navigate back in browser history.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={},
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="flag_visual_bug",
                description="Report a visual or UX bug found on the current page.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "description": genai.protos.Schema(type=genai.protos.Type.STRING, description="Clear description of the bug"),
                        "severity": genai.protos.Schema(type=genai.protos.Type.STRING, description="critical, high, medium, or low"),
                        "x": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="X coordinate of bug, -1 if N/A"),
                        "y": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Y coordinate of bug, -1 if N/A"),
                    },
                    required=["description", "severity"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="mark_test_complete",
                description="Call this ONLY when testing is fully done. Ends the session.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "summary": genai.protos.Schema(type=genai.protos.Type.STRING, description="Brief summary of what was tested"),
                        "bugs_found": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Total bugs found"),
                    },
                    required=["summary", "bugs_found"],
                ),
            ),
        ]
    )

    return genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[tools],
    )


# ─────────────────────────────────────────────────────────────────────────────
# REST Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = Path("static") / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Visual QA Sniper — backend running.</h1>")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "visual-qa-sniper", "version": "1.0.0"}


@app.get("/sessions")
async def list_sessions():
    return JSONResponse({"sessions": session_mgr.get_all_sessions()})


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = session_mgr.get_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse(session)


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket — Action-Observation Loop
# ─────────────────────────────────────────────────────────────────────────────

@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    print("[WS] Client connected.")

    browser: BrowserEngine | None = None
    stop_requested = False
    session_id: str | None = None

    async def send(msg: dict):
        try:
            await websocket.send_text(json.dumps(msg))
        except Exception:
            pass

    async def stream_screenshot(b64: str):
        await send({"type": "screenshot", "data": b64, "url": browser.current_url if browser else ""})

    try:
        while True:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=120)
            msg = json.loads(raw)

            if msg.get("type") == "ping":
                await send({"type": "pong"})
                continue

            if msg.get("type") == "stop":
                stop_requested = True
                if browser:
                    await browser.close()
                    browser = None
                await send({"type": "stopped"})
                continue

            if msg.get("type") == "start":
                url  = msg.get("url", "").strip()
                goal = msg.get("goal", "Explore the UI and report any visual bugs.").strip()

                if not url:
                    await send({"type": "error", "message": "No URL provided."})
                    continue

                stop_requested = False
                if browser:
                    await browser.close()

                session_id = session_mgr.new_session(url, goal)
                await send({"type": "session_start", "session_id": session_id, "url": url, "goal": goal})

                browser = BrowserEngine()
                await browser.start()

                # Navigate to initial URL
                await send({"type": "action", "step": 0, "tool": "navigate_to_url",
                            "args": {"url": url}, "description": f"Navigating to {url}"})
                b64 = await browser.navigate(url)
                await stream_screenshot(b64)

                # Build Gemini model + chat session
                model = build_model()
                chat = model.start_chat(history=[])

                step = 1
                bugs: list[dict] = []
                MAX_STEPS = 30

                while step <= MAX_STEPS and not stop_requested:
                    img_bytes = base64.b64decode(b64)

                    prompt_parts = [
                        f"Testing goal: {goal}\nCurrent URL: {browser.current_url}\n"
                        f"Step {step}/{MAX_STEPS}. Analyze the screenshot and call the next action function.",
                        {"mime_type": "image/jpeg", "data": img_bytes},
                    ]

                    try:
                        response = await asyncio.to_thread(chat.send_message, prompt_parts)
                    except Exception as e:
                        await send({"type": "error", "message": f"Gemini API error: {e}"})
                        break

                    # Extract function call from response
                    tool_name: str | None = None
                    tool_args: dict = {}

                    for candidate in response.candidates:
                        for part in candidate.content.parts:
                            if hasattr(part, "function_call") and part.function_call:
                                fc = part.function_call
                                tool_name = fc.name
                                tool_args = dict(fc.args) if fc.args else {}
                                break
                        if tool_name:
                            break

                    if not tool_name:
                        # Model returned text — agent is thinking or done
                        text = response.text if hasattr(response, "text") else ""
                        if text:
                            await send({"type": "action", "step": step, "tool": "thinking",
                                        "args": {}, "description": text[:120]})
                        step += 1
                        await asyncio.sleep(0.5)
                        continue

                    # Notify frontend of the action
                    await send({
                        "type": "action", "step": step, "tool": tool_name,
                        "args": tool_args,
                        "description": _describe(tool_name, tool_args),
                    })

                    session_mgr.add_step(session_id, {"step": step, "tool": tool_name, "args": tool_args})

                    # ── Dispatch to BrowserEngine ──────────────────────
                    if tool_name == "navigate_to_url":
                        b64 = await browser.navigate(tool_args.get("url", url))
                        await stream_screenshot(b64)

                    elif tool_name == "click_element":
                        b64 = await browser.click(int(tool_args.get("x", 0)), int(tool_args.get("y", 0)))
                        await stream_screenshot(b64)

                    elif tool_name == "type_into_field":
                        b64 = await browser.type_text(str(tool_args.get("text", "")))
                        await stream_screenshot(b64)

                    elif tool_name == "press_keyboard_key":
                        b64 = await browser.press_key(str(tool_args.get("key", "Enter")))
                        await stream_screenshot(b64)

                    elif tool_name == "scroll_page":
                        b64 = await browser.scroll(
                            str(tool_args.get("direction", "down")),
                            int(tool_args.get("amount", 300)),
                        )
                        await stream_screenshot(b64)

                    elif tool_name == "hover_over_element":
                        b64 = await browser.hover(int(tool_args.get("x", 0)), int(tool_args.get("y", 0)))
                        await stream_screenshot(b64)

                    elif tool_name == "go_back":
                        b64 = await browser.go_back()
                        await stream_screenshot(b64)

                    elif tool_name == "flag_visual_bug":
                        bug = {
                            "description": str(tool_args.get("description", "")),
                            "severity":    str(tool_args.get("severity", "medium")),
                            "x":           int(tool_args.get("x", -1)),
                            "y":           int(tool_args.get("y", -1)),
                            "step":        step,
                            "screenshot":  b64,
                        }
                        bugs.append(bug)
                        session_mgr.add_bug(session_id, bug)
                        await send({
                            "type":        "bug",
                            "description": bug["description"],
                            "severity":    bug["severity"],
                            "x":           bug["x"],
                            "y":           bug["y"],
                            "step":        step,
                            "screenshot":  bug["screenshot"],
                        })
                        # Continue loop without advancing step counter

                    elif tool_name == "mark_test_complete":
                        summary    = str(tool_args.get("summary", "Test complete."))
                        bugs_found = int(tool_args.get("bugs_found", len(bugs)))
                        session_mgr.complete_session(session_id, summary, bugs_found)
                        await send({"type": "complete", "summary": summary,
                                    "bugs_found": bugs_found, "session_id": session_id})
                        break

                    step += 1
                    await asyncio.sleep(0.05)

                # Auto-complete if max steps reached
                if step > MAX_STEPS and not stop_requested:
                    session_mgr.complete_session(
                        session_id, f"Auto-completed after {MAX_STEPS} steps.", len(bugs))
                    await send({"type": "complete",
                                "summary": f"Auto-completed after {MAX_STEPS} steps.",
                                "bugs_found": len(bugs), "session_id": session_id})

    except WebSocketDisconnect:
        print("[WS] Client disconnected.")
    except asyncio.TimeoutError:
        print("[WS] Receive timed out.")
    except Exception as e:
        print(f"[WS] Unhandled error: {e}")
        try:
            await send({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if browser:
            await browser.close()


# ─────────────────────────────────────────────────────────────────────────────
def _describe(tool: str, args: dict) -> str:
    return {
        "navigate_to_url":   f"Navigating to {args.get('url','')}",
        "click_element":     f"Clicking at ({args.get('x')}, {args.get('y')})",
        "type_into_field":   f'Typing: "{args.get("text","")}"',
        "press_keyboard_key":f"Pressing {args.get('key','Enter')}",
        "scroll_page":       f"Scrolling {args.get('direction','down')} {args.get('amount',300)}px",
        "hover_over_element":f"Hovering at ({args.get('x')}, {args.get('y')})",
        "go_back":           "Going back",
        "flag_visual_bug":   f"🐛 [{args.get('severity','?').upper()}] {args.get('description','')}",
        "mark_test_complete":f"✅ {args.get('summary','')}",
        "thinking":          "Agent analyzing…",
    }.get(tool, tool)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)