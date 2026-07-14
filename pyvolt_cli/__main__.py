"""Entry point for the ``pyvolt`` command (``[project.scripts]``)."""
from __future__ import annotations

from .app import app


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
