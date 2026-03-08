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

    response = context.request.get(
        "https://ust.space/review/COMP1021/get",
        params={
            "single": "false",
            "composer": "false",
            "preferences[sort]": "0",
            "preferences[filterInstructor]": "0",
            "preferences[filterSemester]": "0",
            "preferences[filterRating]": "0",
        },
    )
    print("status", response.status)
    text = response.text()
    print(text[:2000])

    browser.close()
