import sys
from pathlib import Path

# Make test helpers (fakes.py) importable under --import-mode=importlib.
sys.path.insert(0, str(Path(__file__).parent))
