"""python -m setup  ->  the setup wizard (setup/wizard.py)."""
import sys

from setup.wizard import run

if __name__ == "__main__":
    sys.exit(run())
