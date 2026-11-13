#!/usr/bin/env python3
"""run CPU verification in a fresh isolated source copy."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    """delegate explicit execution and exact failure reporting to the acceptance runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=Path('/tmp/cpu5-verification'))
    args = parser.parse_args()
    command = [sys.executable, str(ROOT / 'microcontroller/release/acceptance.py'),
               '--suite', 'all', '--output', str(args.build.absolute()), '--execute']
    result = subprocess.run(command, cwd=ROOT, check=False)
    raise SystemExit(result.returncode)


# importing the wrapper never starts tools or creates evidence.
if __name__ == '__main__':
    main()
