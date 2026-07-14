# pyvolt-cli

The command-line companion to [Pyvolt](https://pyvolt.com) — managed Python
deployments on infrastructure you actually own.

```bash
uv tool install pyvolt-cli   # or: pipx install pyvolt-cli
pyvolt login                 # browser approval, no password in the terminal
pyvolt deploy myapp --follow
```

| Command | What it does |
|---|---|
| `pyvolt login` / `logout` / `whoami` | Device-flow auth (token stored in `~/.config/pyvolt/`, mode 600) |
| `pyvolt servers` / `pyvolt apps` | Inventory with live status |
| `pyvolt deploy APP [--follow]` | Trigger a deployment, optionally streaming the log |
| `pyvolt deployments APP` | Recent deployment history |
| `pyvolt env APP list\|set K=V…\|rm K` | Environment variables — pushed and app restarted |
| `pyvolt ps APP [restart NAME]` | Background processes with live systemd state |
| `pyvolt logs APP [-p NAME] [-n N]` | Tail the app's journal |
| `pyvolt open APP` | Jump to the dashboard |

`APP` is the app's domain, or any unambiguous fragment of it.

Full guide: [pyvolt.com/docs/cli](https://pyvolt.com/docs/cli/) · HTTP API:
[pyvolt.com/api/docs](https://pyvolt.com/api/docs)

## Development

```bash
uv sync
uv run pytest
```

## License

MIT. See [LICENSE](LICENSE).
