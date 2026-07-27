"""pyvolt-cli: the terminal companion to Pyvolt — managed Python deployments
on infrastructure you actually own. Docs: https://pyvolt.com/docs/cli/"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pyvolt-cli")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0.dev0"
