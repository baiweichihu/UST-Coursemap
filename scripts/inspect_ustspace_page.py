import os
from playwright.sync_api import sync_playwright

username = os.environ["USTSPACE_USERNAME"]
password = os.environ["USTSPACE_PASSWORD"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    page.goto("https://ust.space/login", wait_until="domcontentloaded")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-btn")
    page.wait_for_timeout(2000)

    page.goto("https://ust.space/review/COMP1021", wait_until="domcontentloaded")
    html = page.content()
    with open("tmp_ustspace_logged_comp1021.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("saved", len(html))
    browser.close()
