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
| `pyvolt deploy DOMAIN [--follow]` | Trigger a deployment, optionally streaming the log |
| `pyvolt deployments DOMAIN` | Recent deployment history |
| `pyvolt env DOMAIN list\|get K\|set K=V…\|rm K` | Environment variables — pushed and app restarted |
| `pyvolt ps DOMAIN [restart NAME]` | Background processes with live systemd state |
| `pyvolt logs DOMAIN [-p NAME] [-n N]` | Tail the app's journal |
| `pyvolt bans SERVER` | IPs banned by fail2ban, your own flagged |
| `pyvolt unban SERVER [IP] [--me]` | Lift a ban — `--me` unbans your own IP, even while it's banned |
| `pyvolt ssh SERVER [--app DOMAIN]` | Open a shell on the server (as the `pyvolt` user); `--app` cds into the app dir |
| `pyvolt open DOMAIN` | Jump to the dashboard |

`DOMAIN` is the app's domain, or any unambiguous fragment of it — domains
are unique across the platform, so no server qualifier is ever needed.

Full guide: [pyvolt.com/docs/cli](https://pyvolt.com/docs/cli/) · HTTP API:
[pyvolt.com/api/docs](https://pyvolt.com/api/docs)

## Development

```bash
uv sync
uv run pytest
```

## License

MIT. See [LICENSE](LICENSE).
