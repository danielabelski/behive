"""Opt-in Playwright checks: BEHIVE_LANDING_URL=http://127.0.0.1:4327 npm run test:browser.
Uses installed Python Playwright + Chromium. Does not contact engine or external sites.
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

URL = os.environ.get("BEHIVE_LANDING_URL", "")
if not URL:
    raise SystemExit("Set BEHIVE_LANDING_URL to a running local landing server (opt-in).")
OUT = Path(__file__).resolve().parents[1] / "artifacts"
OUT.mkdir(exist_ok=True)
results = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for name, width, height in [("desktop", 1440, 900), ("mobile", 390, 844), ("narrow", 320, 740)]:
        context = browser.new_context(viewport={"width": width, "height": height}, permissions=["clipboard-read", "clipboard-write"], service_workers="block")
        # No remote font dependency or incidental API traffic. Use system font fallback.
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(URL) else route.fulfill(status=200, content_type="text/css", body=""))
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        record = {"viewport": name, "size": [width, height], "checks": [], "errors": errors}
        try:
            response = page.goto(URL, wait_until="networkidle")
            assert response is not None and response.status == 200
            expect(page.get_by_text("v0.6.0 — Open Source (MIT)")).to_be_visible()
            subheadline = page.locator('body > section').first.locator('p').filter(has_text='Feed it a question.').inner_text()
            assert 'scored claims, entity graphs, and a synthesized report' in ' '.join(subheadline.split()), f'Inline word spacing missing: {subheadline}'
            record['checks'].append('subheadline inline word spacing')
            hero_bounds = page.locator('body > section').first.locator(':scope > div.relative').bounding_box()
            assert hero_bounds and hero_bounds['x'] >= 0 and hero_bounds['x'] + hero_bounds['width'] <= width + 1, f'Clipped hero container: {hero_bounds}'
            record['checks'].append('hero content fits viewport')
            page.wait_for_function("document.querySelector('#install astro-island')?.hasAttribute('ssr') === false")
            page.locator('#install').scroll_into_view_if_needed()
            page.get_by_role('button', name='Copy to clipboard').first.click()
            expect(page.get_by_text('Copied!', exact=True)).to_be_visible()
            assert page.evaluate('navigator.clipboard.readText()') == 'pip install behive==0.6.0'
            record['checks'].append('install clipboard and feedback')
            if width < 768:
                page.evaluate('window.scrollTo(0,0)')
                toggle = page.locator('#mobile-toggle')
                expect(toggle).to_have_attribute('aria-expanded', 'false')
                assert page.locator('#mobile-nav').evaluate('(node) => node.inert')
                toggle.click()
                expect(toggle).to_have_attribute('aria-expanded', 'true')
                page.wait_for_timeout(400)
                menu_bounds = page.locator('#mobile-nav').bounding_box()
                assert menu_bounds and menu_bounds['height'] >= height - 65, f'Menu backdrop does not cover links: {menu_bounds}'
                record['checks'].append('menu backdrop covers viewport')
                page.screenshot(path=str(OUT / f'{name}-menu.png'))
                page.locator('#mobile-nav').get_by_role('link', name='Capabilities').click()
                expect(toggle).to_have_attribute('aria-expanded', 'false')
                assert page.url.endswith('#capabilities')
                toggle.click()
                page.keyboard.press('Escape')
                expect(toggle).to_have_attribute('aria-expanded', 'false')
                record['checks'].append('mobile menu open, navigate, close, Escape, inert')
            else:
                page.locator('nav').get_by_role('link', name='Capabilities').first.click()
                assert page.url.endswith('#capabilities')
                record['checks'].append('desktop section navigation')
            # Reveal every lazy island before the full-page screenshot.
            for section in page.locator('body > section').all():
                section.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
            page.get_by_role('button', name='Copy to clipboard').last.click()
            assert page.evaluate('navigator.clipboard.readText()') == 'pip install behive==0.6.0'
            record['checks'].append('footer clipboard')
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Horizontal page overflow'
            assert page.locator('img').evaluate_all('(images) => images.every(i => i.complete && i.naturalWidth > 0)'), 'Broken image'
            assert page.locator('a[href^="#"]').evaluate_all('(links) => links.every(a => document.querySelector(a.getAttribute("href")))'), 'Broken anchor'
            text = page.locator('body').inner_text()
            for claim in ['53K', '127K', 'Benchmarks', 'Zero hallucination', '500K units', 'works everywhere']:
                assert claim not in text, claim
            assert 'Schematic example — not a research result' in text
            record['checks'].append('content, image loading, anchors, no horizontal overflow')
            page.get_by_role('button', name='Scroll to top').click()
            page.wait_for_function('window.scrollY < 10')
            page.wait_for_timeout(2200)
            page.screenshot(path=str(OUT / f'{name}-full.png'), full_page=True)
            page.screenshot(path=str(OUT / f'{name}-hero.png'))
            record['checks'].append('scroll-to-top and screenshots')
            assert not errors, errors
            record['passed'] = True
        except Exception as exc:
            record['passed'] = False
            record['failure'] = str(exc)
            page.screenshot(path=str(OUT / f'{name}-failure.png'), full_page=True)
            results.append(record)
            (OUT / 'browser-results.json').write_text(json.dumps(results, indent=2))
            raise
        results.append(record)
        context.close()
    browser.close()
(OUT / 'browser-results.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
