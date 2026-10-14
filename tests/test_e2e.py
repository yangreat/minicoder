"""End-to-end test for the web console using Playwright (optional)."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from minicoder.demo import ORIGINAL_CALCULATOR, restore_toy_calculator, toy_calculator_dir

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


CALCULATOR = toy_calculator_dir() / "calculator.py"


@pytest.fixture
def reset_calculator() -> None:
    restore_toy_calculator()
    yield
    restore_toy_calculator()


@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
@pytest.mark.asyncio
async def test_web_console_loads() -> None:
    """Test that the web console loads successfully."""
    backend = subprocess.Popen(
        ["python3", "-m", "minicoder.cli", "serve", "--host", "0.0.0.0", "--port", "8001"],
        cwd="/workspace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    await asyncio.sleep(3)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            response = await page.goto("http://localhost:8001/")
            assert response is not None
            assert response.status == 200
            await page.wait_for_selector(".app-header", timeout=10000)
            title = await page.title()
            assert "MiniCoder" in title
            assert await page.locator("#task").count() > 0
            await browser.close()
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()
            backend.wait()


@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
@pytest.mark.asyncio
async def test_demo_mode_full_flow(reset_calculator: None) -> None:
    """Demo mode streams events, renders the DAG, shows a real diff, and rollback restores the file."""
    assert "Cannot divide by zero" not in CALCULATOR.read_text()

    backend = subprocess.Popen(
        ["python3", "-m", "minicoder.cli", "serve", "--host", "0.0.0.0", "--port", "8001"],
        cwd="/workspace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    await asyncio.sleep(3)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1400, "height": 900})
            page = await context.new_page()
            page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))

            await page.goto("http://localhost:8001/")
            await page.wait_for_selector(".app-header", timeout=10000)

            await page.fill("#task", "Fix the divide-by-zero bug in calculator.py")
            checkbox = page.locator('input[type="checkbox"]')
            if not await checkbox.is_checked():
                await page.evaluate("document.querySelector('input[type=\"checkbox\"]').click()")

            await page.click('button:has-text("Start Run")')

            await page.wait_for_selector('[data-testid="event-item"]', timeout=25000)
            await page.wait_for_function(
                "document.querySelectorAll('[data-testid=\"event-item\"]').length >= 6",
                timeout=25000,
            )
            await page.wait_for_function(
                "document.querySelectorAll('.react-flow__node').length >= 3",
                timeout=25000,
            )
            node_count = await page.locator(".react-flow__node").count()
            assert node_count >= 3

            await page.wait_for_function(
                """() => document.body.innerText.includes('Cannot divide by zero')
                    || document.body.innerText.includes('apply_patch')""",
                timeout=20000,
            )

            # Wait until the toy file is actually patched (agent finished the write).
            for _ in range(40):
                if "Cannot divide by zero" in CALCULATOR.read_text():
                    break
                await asyncio.sleep(0.25)
            assert "Cannot divide by zero" in CALCULATOR.read_text()

            await page.wait_for_selector('[data-testid="diff-viewer"]', timeout=10000)
            await page.wait_for_selector('[data-testid="reject-btn"]', timeout=10000)
            await page.wait_for_function(
                "() => document.body.innerText.includes('Cannot divide by zero')",
                timeout=20000,
            )
            await asyncio.sleep(1.2)

            docs = Path("/workspace/docs/images")
            docs.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(docs / "console-screenshot.png"), full_page=True)
            await page.locator('[data-testid="diff-viewer"]').screenshot(
                path=str(docs / "diff-viewer.png")
            )

            await page.click('[data-testid="reject-btn"]')
            await asyncio.sleep(1)
            assert "Cannot divide by zero" not in CALCULATOR.read_text()
            assert "return a / b" in CALCULATOR.read_text()

            await browser.close()
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()
            backend.wait()
        restore_toy_calculator()
