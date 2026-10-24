#!/usr/bin/env python3
import os
import subprocess
import sys

def main():
    if len(sys.argv) <= 1:
        print("Usage: soffice.py [ARGS...]")
        sys.exit(1)
    cmd = ["soffice"] + sys.argv[1:]
    env = os.environ.copy()
    result = subprocess.run(cmd, check=False, env=env)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
