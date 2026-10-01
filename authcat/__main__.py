"""``python -m authcat <command>`` -- the same as the ``authcat`` command."""

import sys

from authcat.cli import main

sys.exit(main())
