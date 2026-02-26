# vision_engine.py
# Async Playwright browser engine — the "hands and eyes" of the agent.
# Viewport is locked to 1280×720 so Gemini's X/Y coordinates are always deterministic.

import asyncio
import base64
from pathlib import Path
from playwright.async_api import async_playwright, Page, Browser, Playwright


class BrowserEngine:
    """Manages a headless Chromium browser for visual UI interaction."""

    VIEWPORT = {"width": 1280, "height": 720}

    def __init__(self):
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self.page: Page | None = None
        self.current_url: str = ""

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch the headless browser and open a fresh tab."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = await self._browser.new_context(
            viewport=self.VIEWPORT,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self.page = await context.new_page()
        print("[BrowserEngine] Started. Viewport: 1280×720")

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        print("[BrowserEngine] Closed.")

    # ──────────────────────────────────────────────────────────────────────────
    # Actions — each action returns a base64-encoded JPEG screenshot
    # ──────────────────────────────────────────────────────────────────────────

    async def navigate(self, url: str) -> str:
        """Navigate to a URL and return a screenshot."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self.current_url = url
        try:
            await self.page.goto(url, wait_until="networkidle", timeout=20_000)
        except Exception:
            # Some pages never hit networkidle — fall back to load
            await self.page.goto(url, wait_until="load", timeout=20_000)
        await self.page.wait_for_timeout(800)
        return await self._capture()

    async def click(self, x: int, y: int) -> str:
        """Click at exact pixel coordinates and return updated screenshot."""
        await self.page.mouse.click(x, y)
        await self.page.wait_for_timeout(1_200)
        self.current_url = self.page.url
        return await self._capture()

    async def type_text(self, text: str) -> str:
        """Type text into the currently focused element."""
        await self.page.keyboard.type(text, delay=40)
        await self.page.wait_for_timeout(400)
        return await self._capture()

    async def press_key(self, key: str) -> str:
        """Press a keyboard key (e.g. 'Enter', 'Tab', 'Escape')."""
        await self.page.keyboard.press(key)
        await self.page.wait_for_timeout(800)
        return await self._capture()

    async def scroll(self, direction: str, amount: int = 300) -> str:
        """Scroll the page up or down by a pixel amount."""
        dy = amount if direction == "down" else -amount
        await self.page.mouse.wheel(0, dy)
        await self.page.wait_for_timeout(500)
        return await self._capture()

    async def hover(self, x: int, y: int) -> str:
        """Move mouse to coordinates (reveals tooltips/dropdowns)."""
        await self.page.mouse.move(x, y)
        await self.page.wait_for_timeout(600)
        return await self._capture()

    async def go_back(self) -> str:
        """Navigate back in browser history."""
        await self.page.go_back(wait_until="networkidle", timeout=10_000)
        await self.page.wait_for_timeout(600)
        return await self._capture()

    async def capture(self) -> str:
        """Force-capture the current viewport without performing any action."""
        return await self._capture()

    # ──────────────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────────────

    async def _capture(self) -> str:
        """Return a base64-encoded JPEG screenshot of the current viewport."""
        raw: bytes = await self.page.screenshot(
            type="jpeg",
            quality=82,
            clip={"x": 0, "y": 0, "width": 1280, "height": 720},
        )
        return base64.b64encode(raw).decode("utf-8")

    @property
    def is_ready(self) -> bool:
        return self.page is not None and not self.page.is_closed()
