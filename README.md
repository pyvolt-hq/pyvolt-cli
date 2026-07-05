# pyvolt-cli

The terminal companion to [pyvolt](https://pyvolt.com): managed Python deployments on infrastructure you actually own.

## Status

This is a **placeholder release (0.0.1)**. It installs the `pyvolt` command onto `$PATH` and prints a "coming soon" banner. Real subcommands (`pyvolt deploy`, `pyvolt logs`, `pyvolt scale`, and friends) land in a future release.

Follow along at:

- Website: <https://pyvolt.com>
- Repository: <https://github.com/pyvolt-hq/pyvolt-cli>
- Issues: <https://github.com/pyvolt-hq/pyvolt-cli/issues>

## Install

```bash
pip install pyvolt-cli
```

The distribution name on PyPI is `pyvolt-cli`; the installed command on your `$PATH` is `pyvolt`.

## Verify

```bash
pyvolt
```

Prints the version banner. If you see it, the entry point is wired correctly.

## Requires

Python 3.10 or newer.

## License

MIT. See [LICENSE](LICENSE).
