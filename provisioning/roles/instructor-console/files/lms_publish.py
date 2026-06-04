#!/usr/bin/env python3
"""
PUC2-Sub Case 2a — LMS Content Publisher

Assembles /tmp/lms-build/index.html from the editable module content files
and the HTML wrapper template, so the instructor can update course content
without re-running the full Ansible playbook.

Editable files (one per module — HTML fragments, card content only):
  /opt/instructor-console/lms-content/module1.html
  /opt/instructor-console/lms-content/module2.html
  /opt/instructor-console/lms-content/module3.html

Fixed file (CSS, nav, exercise tab, JavaScript — edit with care):
  /opt/instructor-console/lms-content/wrapper.html

Usage:
  python3 /opt/instructor-console/lms_publish.py

After running, deploy with the PUBLISH_LMS shortcut or manually:
  scp /tmp/lms-build/index.html <lms-user>@lms.internal:/srv/lms/index.html
"""

import sys
from pathlib import Path

CONTENT_DIR  = Path("/opt/instructor-console/lms-content")
WRAPPER_FILE = CONTENT_DIR / "wrapper.html"
OUTPUT_FILE  = Path("/tmp/lms-build/index.html")
MODULES      = ["module1", "module2", "module3"]


def main():
    if not WRAPPER_FILE.exists():
        sys.exit(f"Wrapper template not found: {WRAPPER_FILE}\nRe-run the Ansible playbook to restore it.")

    missing = [m for m in MODULES if not (CONTENT_DIR / f"{m}.html").exists()]
    if missing:
        sys.exit(
            f"Missing module content file(s): "
            + ", ".join(f"{m}.html" for m in missing)
            + f"\nExpected in {CONTENT_DIR}"
        )

    page = WRAPPER_FILE.read_text(encoding="utf-8")

    for module_id in MODULES:
        marker  = f"<!-- {module_id.upper()}_CONTENT -->"
        content = (CONTENT_DIR / f"{module_id}.html").read_text(encoding="utf-8")
        if marker not in page:
            print(f"[!] Warning: marker {marker} not found in wrapper.html — {module_id} skipped.", file=sys.stderr)
            continue
        page = page.replace(marker, content.strip())

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(page, encoding="utf-8")
    print(f"[+] Built {OUTPUT_FILE}  ({OUTPUT_FILE.stat().st_size} bytes)")
    print(f"    Modules included: {', '.join(MODULES)}")


if __name__ == "__main__":
    main()
