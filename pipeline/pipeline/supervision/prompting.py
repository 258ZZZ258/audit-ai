"""Keep extraction, omission review and verification on one status policy."""

from pathlib import Path


def load_prompt(name):
    root = Path(__file__).parent
    return (root / name).read_text("utf-8") + "\n" + (root / "status-policy.txt").read_text("utf-8")
