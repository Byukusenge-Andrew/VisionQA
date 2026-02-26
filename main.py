# main.py
# Visual QA Sniper — FastAPI backend
# Uses google-genai (>=1.0) SDK + Playwright for the action-observation loop

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
import uvicorn

# ── Google GenAI SDK (new unified SDK — google-genai >= 1.0) ─────────────────
from google import genai
from google.genai import types as genai_types

# ── Local modules ─────────────────────────────────────────────────────────────
from vision_engine import BrowserEngine
from session_manager import SessionManager

# ─────────────────────────────────────────────────────────────────────────────
# App + Client Setup
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Visual QA Sniper API", version="1.0.0")
session_mgr = SessionManager()
Path("static").mkdir(exist_ok=True)

API_KEY = os.environ.get("GOOGLE_API_KEY", "")
client = genai.Client(api_key=API_KEY)

MODEL = "gemini-2.0-flash"

SYSTEM_INSTRUCTION = """
You are **Visual QA Sniper**, an elite autonomous web UI testing agent.
You interact with web applications ENTIRELY through computer vision — no DOM access.

## Workflow
1. OBSERVE: Carefully study the 1280×720 screenshot.
2. PLAN: Choose the single best next action toward the goal.
3. ACT: Call exactly ONE function. Don't narrate — just call it.
4. REPEAT until goal is complete or fully explored.

## Rules
- Never ask for permission. Execute immediately.
- Estimate the precise CENTER pixel of buttons/inputs/links.
- After typing in a field, press Enter OR click the submit button.
- Scroll to find content below the fold.
- Flag ANY visual defect immediately: overlapping text, broken images,
  misaligned elements, poor contrast, cut-off content.
- When fully done, call mark_test_complete.

## Bug severity
- critical: Blocks a core user task
- high: Major UX issue  
- medium: Noticeable defect
- low: Cosmetic only

## Coordinates
(0,0) = top-left corner. (1280,720) = bottom-right corner.
"""

# ── Tool declarations ─────────────────────────────────────────────────────────
QA_TOOLS = [
    genai_types.Tool(function_declarations=[
        genai_types.FunctionDeclaration(
            name="navigate_to_url",
            description="Navigate the browser to a URL.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"url": genai_types.Schema(type="STRING", description="Full URL with https://")},
                required=["url"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="click_element",
            description="Click a UI element at pixel coordinates (center of element).",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "x": genai_types.Schema(type="INTEGER", description="X pixel (0-1280)"),
                    "y": genai_types.Schema(type="INTEGER", description="Y pixel (0-720)"),
                },
                required=["x", "y"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="type_into_field",
            description="Type text into the currently focused input field. Click the field first.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"text": genai_types.Schema(type="STRING", description="Text to type")},
                required=["text"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="press_keyboard_key",
            description="Press a keyboard key: Enter, Tab, Escape, ArrowDown, etc.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={"key": genai_types.Schema(type="STRING", description="Key name")},
                required=["key"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="scroll_page",
            description="Scroll the page to reveal more content.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "direction": genai_types.Schema(type="STRING", description="'up' or 'down'"),
                    "amount": genai_types.Schema(type="INTEGER", description="Pixels, default 300"),
                },
                required=["direction"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="hover_over_element",
            description="Hover over coordinates to reveal dropdowns or tooltips.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "x": genai_types.Schema(type="INTEGER"),
                    "y": genai_types.Schema(type="INTEGER"),
                },
                required=["x", "y"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="go_back",
            description="Navigate back in browser history.",
            parameters=genai_types.Schema(type="OBJECT", properties={}),
        ),
        genai_types.FunctionDeclaration(
            name="flag_visual_bug",
            description="Report a visual or UX bug found on the page.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "description": genai_types.Schema(type="STRING", description="Clear bug description"),
                    "severity":    genai_types.Schema(type="STRING", description="critical/high/medium/low"),
                    "x": genai_types.Schema(type="INTEGER", description="X coord of bug, -1 if N/A"),
                    "y": genai_types.Schema(type="INTEGER", description="Y coord of bug, -1 if N/A"),
                },
                required=["description", "severity"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="mark_test_complete",
            description="Call when testing is fully done. Ends the session.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "summary":    genai_types.Schema(type="STRING", description="Summary of what was tested"),
                    "bugs_found": genai_types.Schema(type="INTEGER", description="Total bugs flagged"),
                },
                required=["summary", "bugs_found"],
            ),
        ),
    ])
]

CONFIG = genai_types.GenerateContentConfig(
    system_instruction=SYSTEM_INSTRUCTION,
    tools=QA_TOOLS,
    temperature=0.1,  # Low temperature for deterministic actions
)

# ─────────────────────────────────────────────────────────────────────────────
# REST Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = Path("static") / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Visual QA Sniper — backend running.</h1><p>Place index.html in /static/</p>")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "visual-qa-sniper", "version": "1.0.0"}


@app.get("/sessions")
async def list_sessions():
    return JSONResponse({"sessions": session_mgr.get_all_sessions()})


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    sess = session_mgr.get_session(session_id)
    if not sess:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(sess)


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
    # Gemini chat history (multimodal, persisted across turns)
    chat_history: list = []

    async def send(msg: dict):
        try:
            await websocket.send_text(json.dumps(msg))
        except Exception:
            pass

    async def push_screenshot(b64: str):
        await send({"type": "screenshot", "data": b64,
                    "url": browser.current_url if browser else ""})

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
                chat_history.clear()
                await send({"type": "stopped"})
                continue

            if msg.get("type") == "start":
                url  = msg.get("url", "").strip()
                goal = msg.get("goal", "Explore the UI and find visual bugs.").strip()

                if not url:
                    await send({"type": "error", "message": "No URL provided."})
                    continue

                stop_requested = False
                chat_history.clear()

                if browser:
                    await browser.close()

                session_id = session_mgr.new_session(url, goal)
                await send({"type": "session_start", "session_id": session_id,
                            "url": url, "goal": goal})

                # Launch browser
                browser = BrowserEngine()
                await browser.start()

                await send({"type": "action", "step": 0, "tool": "navigate_to_url",
                            "args": {"url": url}, "description": f"Navigating to {url}"})
                b64 = await browser.navigate(url)
                await push_screenshot(b64)

                step = 1
                bugs: list[dict] = []
                MAX_STEPS = 30

                while step <= MAX_STEPS and not stop_requested:
                    img_bytes = base64.b64decode(b64)

                    # Build prompt text (context-rich per step)
                    prompt_text = (
                        f"Testing goal: {goal}\n"
                        f"Current URL: {browser.current_url}\n"
                        f"Step {step}/{MAX_STEPS}. "
                        "Analyze the screenshot carefully and call the next action function."
                    )

                    # Call Gemini — stateless (screenshot + context each turn)
                    contents = [
                        {
                            "role": "user",
                            "parts": [
                                {"text": prompt_text},
                                {"inline_data": {
                                    "mime_type": "image/jpeg",
                                    "data": img_bytes,
                                }},
                            ],
                        }
                    ]
                    # Call Gemini — with automatic 429 retry
                    response = None
                    for attempt in range(3):
                        try:
                            response = await asyncio.to_thread(
                                client.models.generate_content,
                                model=MODEL,
                                contents=contents,
                                config=CONFIG,
                            )
                            break  # success
                        except Exception as e:
                            err_str = str(e)
                            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                                # Parse retry delay from error message
                                import re
                                match = re.search(r"retry[^\d]*(\d+)", err_str, re.I)
                                wait_s = int(match.group(1)) + 2 if match else 32
                                if attempt < 2:
                                    await send({"type": "action", "step": step,
                                                "tool": "thinking", "args": {},
                                                "description": f"⏳ Rate limited — retrying in {wait_s}s…"})
                                    await asyncio.sleep(wait_s)
                                else:
                                    await send({"type": "error",
                                                "message": f"API quota exhausted. Please enable billing at console.cloud.google.com or wait and retry. ({wait_s}s cooldown)"})
                                    response = None
                                    break
                            else:
                                await send({"type": "error", "message": f"Gemini API error: {e}"})
                                response = None
                                break
                    if response is None:
                        break


                    # Extract tool call
                    tool_name: str | None = None
                    tool_args: dict = {}

                    if response.candidates:
                        for part in response.candidates[0].content.parts:
                            if part.function_call:
                                tool_name = part.function_call.name
                                tool_args = dict(part.function_call.args or {})
                                break

                    if not tool_name:
                        # Text-only response — model is thinking
                        text = ""
                        try:
                            text = response.text[:140]
                        except Exception:
                            pass
                        await send({"type": "action", "step": step, "tool": "thinking",
                                    "args": {}, "description": text or "Analyzing…"})
                        step += 1
                        await asyncio.sleep(0.5)
                        continue

                    # Notify frontend
                    await send({
                        "type": "action", "step": step,
                        "tool": tool_name, "args": tool_args,
                        "description": _describe(tool_name, tool_args),
                    })
                    session_mgr.add_step(session_id, {"step": step, "tool": tool_name, "args": tool_args})

                    # ── Dispatch to browser ────────────────────────────────
                    if tool_name == "navigate_to_url":
                        b64 = await browser.navigate(tool_args.get("url", url))
                        await push_screenshot(b64)

                    elif tool_name == "click_element":
                        b64 = await browser.click(int(tool_args.get("x", 0)), int(tool_args.get("y", 0)))
                        await push_screenshot(b64)

                    elif tool_name == "type_into_field":
                        b64 = await browser.type_text(str(tool_args.get("text", "")))
                        await push_screenshot(b64)

                    elif tool_name == "press_keyboard_key":
                        b64 = await browser.press_key(str(tool_args.get("key", "Enter")))
                        await push_screenshot(b64)

                    elif tool_name == "scroll_page":
                        b64 = await browser.scroll(
                            str(tool_args.get("direction", "down")),
                            int(tool_args.get("amount", 300)),
                        )
                        await push_screenshot(b64)

                    elif tool_name == "hover_over_element":
                        b64 = await browser.hover(int(tool_args.get("x", 0)), int(tool_args.get("y", 0)))
                        await push_screenshot(b64)

                    elif tool_name == "go_back":
                        b64 = await browser.go_back()
                        await push_screenshot(b64)

                    elif tool_name == "flag_visual_bug":
                        bug = {
                            "description": str(tool_args.get("description", "")),
                            "severity":    str(tool_args.get("severity", "medium")).lower(),
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
                        # Don't advance step — re-analyze after logging bug

                    elif tool_name == "mark_test_complete":
                        summary    = str(tool_args.get("summary", "Test complete."))
                        bugs_found = int(tool_args.get("bugs_found", len(bugs)))
                        session_mgr.complete_session(session_id, summary, bugs_found)
                        await send({"type": "complete", "summary": summary,
                                    "bugs_found": bugs_found, "session_id": session_id})
                        break

                    step += 1
                    await asyncio.sleep(0.05)

                if step > MAX_STEPS and not stop_requested:
                    session_mgr.complete_session(
                        session_id,
                        f"Auto-completed: reached {MAX_STEPS} steps.",
                        len(bugs),
                    )
                    await send({
                        "type": "complete",
                        "summary": f"Auto-completed after {MAX_STEPS} steps.",
                        "bugs_found": len(bugs),
                        "session_id": session_id,
                    })

    except WebSocketDisconnect:
        print("[WS] Client disconnected.")
    except asyncio.TimeoutError:
        print("[WS] Timed out.")
    except Exception as e:
        print(f"[WS] Error: {e}")
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
        "navigate_to_url":   f"Navigating to {args.get('url', '')}",
        "click_element":     f"Clicking at ({args.get('x')}, {args.get('y')})",
        "type_into_field":   f'Typing: "{args.get("text", "")}"',
        "press_keyboard_key":f"Pressing {args.get('key', 'Enter')}",
        "scroll_page":       f"Scrolling {args.get('direction', 'down')} {args.get('amount', 300)}px",
        "hover_over_element":f"Hovering at ({args.get('x')}, {args.get('y')})",
        "go_back":           "Going back",
        "flag_visual_bug":   f"🐛 [{args.get('severity','?').upper()}] {args.get('description', '')}",
        "mark_test_complete":f"✅ {args.get('summary', '')}",
        "thinking":          "Analyzing…",
    }.get(tool, tool)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)