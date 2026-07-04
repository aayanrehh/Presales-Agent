"""Verify the local runtime has the MVP dependencies available."""

from __future__ import annotations

import importlib.util
import sys


REQUIRED_PACKAGES = ("streamlit", "pandas", "pydantic", "docx", "pptx", "reportlab")


def main() -> int:
    missing = [name for name in REQUIRED_PACKAGES if importlib.util.find_spec(name) is None]
    if missing:
        print("Missing packages:", ", ".join(missing))
        print("Install with: pip install -r requirements.txt")
        return 1

    print("All required packages are installed:", ", ".join(REQUIRED_PACKAGES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
