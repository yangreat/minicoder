"""Generate screenshot of the web console."""

import asyncio
import subprocess
import time
from pathlib import Path
from playwright.async_api import async_playwright


async def generate_screenshot():
    """Generate a screenshot of the console in demo mode."""
    print("Building frontend...")
    subprocess.run(
        ["npm", "run", "build"],
        cwd="/workspace/web",
        check=True,
        capture_output=True,
    )
    
    print("Starting backend server...")
    backend = subprocess.Popen(
        ["python3", "-m", "minicoder.cli", "serve", "--host", "0.0.0.0", "--port", "8000"],
        cwd="/workspace",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    
    await asyncio.sleep(5)
    
    try:
        print("Launching browser and capturing screenshot...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1400, "height": 900},
                device_scale_factor=1,
            )
            page = await context.new_page()
            
            await page.goto("http://localhost:8000/")
            
            await page.wait_for_selector('.app-header', timeout=10000)
            
            await page.fill('textarea[id="task"]', 'Fix the bug in calculator.py')
            
            await page.check('input[type="checkbox"]')
            
            await page.click('button[type="submit"]')
            
            await asyncio.sleep(2)
            
            screenshot_path = Path("/workspace/docs/images/console-screenshot.png")
            await page.screenshot(path=str(screenshot_path), full_page=False)
            
            print(f"Screenshot saved to {screenshot_path}")
            
            await browser.close()
    finally:
        print("Stopping backend server...")
        backend.terminate()
        backend.wait()


if __name__ == "__main__":
    asyncio.run(generate_screenshot())
