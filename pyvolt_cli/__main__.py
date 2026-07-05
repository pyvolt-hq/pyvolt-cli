"""Entry point for the ``pyvolt`` command.

The pyproject.toml maps ``[project.scripts] pyvolt`` to :func:`main` in this
module. Running ``pyvolt`` after ``pip install pyvolt-cli`` lands here.
"""

from __future__ import annotations

import sys

from . import __version__


BANNER = f"""
pyvolt {__version__}

Managed Python deployments on infrastructure you actually own.

This CLI is a placeholder release. Real subcommands land in a future
version. Track progress at https://pyvolt.com and
https://github.com/pyvolt-hq/pyvolt-cli.
""".strip()


def main() -> int:
    """Print a coming-soon banner and exit cleanly."""
    print(BANNER)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
