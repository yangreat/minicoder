"""End-to-end test for the web console using Playwright (optional)."""

import asyncio
import subprocess
import pytest
from pathlib import Path

# Check if playwright is available
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
@pytest.mark.asyncio
async def test_web_console_loads():
    """Test that the web console loads successfully."""
    backend = subprocess.Popen(
        ["python3", "-m", "minicoder.cli", "serve", "--host", "0.0.0.0", "--port", "8001"],
        cwd="/workspace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    await asyncio.sleep(5)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Load the app
            response = await page.goto("http://localhost:8001/")
            assert response.status == 200
            
            # Wait for app to load
            await page.wait_for_selector('.app-header', timeout=10000)
            
            # Verify title
            title = await page.title()
            assert "MiniCoder" in title
            
            # Verify main UI elements exist
            task_input = await page.locator('#task').count()
            assert task_input > 0, "Task input should exist"
            
            await browser.close()
            
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()
            backend.wait()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
