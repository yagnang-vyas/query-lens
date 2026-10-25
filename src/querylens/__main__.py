"""Allow ``python -m querylens``."""

import sys

from querylens.cli import main

if __name__ == "__main__":
    sys.exit(main())
