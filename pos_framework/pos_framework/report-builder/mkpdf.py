"""Render a report.html to PDF with the same engine that took the screenshots."""
import os
import sys
import time

from playwright.sync_api import sync_playwright

SRC = sys.argv[1]
OUT = sys.argv[2]

with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_context(viewport={"width": 1100, "height": 1400}).new_page()
    p.goto("file:///" + SRC.replace("\\", "/"), wait_until="networkidle",
           timeout=120000)
    # Force the light palette: a PDF printed in dark mode is unreadable on paper.
    p.emulate_media(media="print", color_scheme="light")
    time.sleep(2)
    p.pdf(path=OUT, format="A4", print_background=True,
          margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
    b.close()

print("%s  %.2f MB" % (OUT, os.path.getsize(OUT) / 1048576.0))
