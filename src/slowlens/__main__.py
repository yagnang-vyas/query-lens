"""Allow ``python -m slowlens``."""

import sys

from slowlens.cli import main

if __name__ == "__main__":
    sys.exit(main())
