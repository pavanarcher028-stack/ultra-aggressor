"""
Run Script — Launch the Autonomous Trading AI
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main

if __name__ == "__main__":
    sys.exit(main())
