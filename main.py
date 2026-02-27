# main.py — Visual QA Sniper (Puter.js hybrid architecture)
# The AI loop now runs CLIENT-SIDE via Puter.js (free Llama 4 / Gemini vision).
# This server only:
#   1. Serves the dashboard HTML
#   2. Manages the Playwright browser headlessly
#   3. Executes actions sent from the frontend and returns screenshots

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

from vision_engine import BrowserEngine
from session_manager import SessionManager

app = FastAPI(title="Visual QA Sniper", version="2.0.0")
session_mgr = SessionManager()
Path("static").mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# REST endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = Path("static") / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Visual QA Sniper backend running.</h1>")


@app.get("/health")
async def health():
    return {"status": "ok", "architecture": "puter-hybrid", "version": "2.0.0"}


@app.get("/sessions")
async def list_sessions():
    return JSONResponse({"sessions": session_mgr.get_all_sessions()})


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    sess = session_mgr.get_session(session_id)
    return JSONResponse(sess) if sess else JSONResponse({"error": "Not found"}, status_code=404)


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket — pure action executor (AI lives in the browser via Puter.js)
# ─────────────────────────────────────────────────────────────────────────────

@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    print("[WS] Client connected.")
    browser: BrowserEngine | None = None
    session_id: str | None = None

    async def send(msg: dict):
        try:
            await websocket.send_text(json.dumps(msg))
        except Exception:
            pass

    async def send_screenshot(b64: str, label: str = ""):
        await send({
            "type": "screenshot",
            "data": b64,
            "url": browser.current_url if browser else "",
            "label": label,
        })

    try:
        while True:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=300)
            msg = json.loads(raw)
            kind = msg.get("type", "")

            # ── Ping/Pong ─────────────────────────────────────
            if kind == "ping":
                await send({"type": "pong"})
                continue

            # ── START: launch browser, navigate to URL ─────────
            if kind == "start":
                url  = msg.get("url", "").strip()
                goal = msg.get("goal", "Explore and find visual bugs.").strip()
                if not url:
                    await send({"type": "error", "message": "No URL provided."}); continue

                if browser:
                    await browser.close()

                session_id = session_mgr.new_session(url, goal)
                await send({"type": "session_start", "session_id": session_id, "url": url, "goal": goal})

                browser = BrowserEngine()
                await browser.start()
                b64 = await browser.navigate(url)
                session_mgr.add_step(session_id, {"step": 0, "tool": "navigate_to_url", "args": {"url": url}})
                await send_screenshot(b64, "Initial page load")

            # ── EXECUTE: run one action, return screenshot ──────
            elif kind == "execute":
                if not browser:
                    await send({"type": "error", "message": "No browser session. Send 'start' first."}); continue

                action = msg.get("action", "")
                args   = msg.get("args", {})
                step   = msg.get("step", 0)

                def _coord(val, max_px: int) -> int:
                    """Safely parse a coordinate: handles None, float 0-1 range, clamps to viewport."""
                    if val is None:
                        return max_px // 2  # centre fallback
                    v = float(val)
                    if 0.0 <= v <= 1.0:   # fractional — convert to pixels
                        v = v * max_px
                    return max(0, min(int(v), max_px))

                session_mgr.add_step(session_id, {"step": step, "tool": action, "args": args})

                b64 = None
                try:
                    if action == "navigate_to_url":
                        b64 = await browser.navigate(str(args.get("url", "")))
                    elif action == "click_element":
                        b64 = await browser.click(_coord(args.get("x"), 1280), _coord(args.get("y"), 720))
                    elif action == "type_into_field":
                        b64 = await browser.type_text(str(args.get("text", "")))
                    elif action == "press_keyboard_key":
                        b64 = await browser.press_key(str(args.get("key", "Enter")))
                    elif action == "scroll_page":
                        b64 = await browser.scroll(str(args.get("direction", "down")), int(args.get("amount", 300)))
                    elif action == "hover_over_element":
                        b64 = await browser.hover(_coord(args.get("x"), 1280), _coord(args.get("y"), 720))
                    elif action == "go_back":
                        b64 = await browser.go_back()
                    elif action == "flag_visual_bug":
                        bug = {
                            "description": str(args.get("description", "")),
                            "severity":    str(args.get("severity", "medium")).lower(),
                            "x": int(args.get("x", -1)),
                            "y": int(args.get("y", -1)),
                            "step": step,
                        }
                        session_mgr.add_bug(session_id, bug)
                        await send({"type": "bug", **bug})
                        # No new screenshot needed for bug reports — re-analyze same page
                        await send({"type": "action_done", "action": action, "step": step, "screenshot": None})
                        continue
                    elif action == "mark_test_complete":
                        summary    = str(args.get("summary", "Test complete."))
                        bugs_found = int(args.get("bugs_found", 0))
                        session_mgr.complete_session(session_id, summary, bugs_found)
                        await send({"type": "complete", "summary": summary,
                                    "bugs_found": bugs_found, "session_id": session_id})
                        if browser:
                            await browser.close(); browser = None
                        continue
                    else:
                        await send({"type": "error", "message": f"Unknown action: {action}"}); continue

                    if b64:
                        await send_screenshot(b64)
                    await send({"type": "action_done", "action": action, "step": step,
                                "screenshot": b64})

                except Exception as e:
                    await send({"type": "error", "message": f"Action failed: {e}"})

            # ── STOP: close browser ────────────────────────────
            elif kind == "stop":
                if browser:
                    await browser.close(); browser = None
                if session_id:
                    session_mgr.complete_session(session_id, "Stopped by user.", 0)
                await send({"type": "stopped"})

    except WebSocketDisconnect:
        print("[WS] Disconnected.")
    except asyncio.TimeoutError:
        print("[WS] Timed out.")
    except Exception as e:
        print(f"[WS] Error: {e}")
        try: await send({"type": "error", "message": str(e)})
        except Exception: pass
    finally:
        if browser: await browser.close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)