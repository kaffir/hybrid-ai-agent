"""
Root conftest.py — ensures src/ is importable during test collection.
"""
import sys
from pathlib import Path

# Add project root to sys.path so 'src' is importable
sys.path.insert(0, str(Path(__file__).parent))
