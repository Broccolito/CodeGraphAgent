"""Allow `python -m codegraphagent` to run the CLI."""

import sys

from codegraphagent.cli import main

sys.exit(main())
