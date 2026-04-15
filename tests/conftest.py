"""Test bootstrap for source-checkout runs.

Allows ``pytest`` from the repo root without requiring an editable install.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
