from __future__ import annotations

import sys
from pathlib import Path


def bootstrap() -> Path:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    src_text = str(src)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
    return root
