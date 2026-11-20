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
| `pyvolt metrics SERVER` | Latest CPU / memory / disk / network snapshot |
| `pyvolt bans SERVER` | IPs banned by fail2ban, your own flagged |
| `pyvolt unban SERVER [IP] [--me]` | Lift a ban — `--me` unbans your own IP, even while it's banned |
| `pyvolt ssh [SERVER] [--app DOMAIN]` | Open a shell on the server (as the `pyvolt` user); `--app` cds into the app's live release |
| `pyvolt run [-a DOMAIN] -- COMMAND` | Run a one-off command in the app's live release with its environment variables, e.g. `-- python manage.py createsuperuser` |
| `pyvolt open DOMAIN` | Jump to the dashboard |

`DOMAIN` is the app's domain, or any unambiguous fragment of it — domains
are unique across the platform, so no server qualifier is ever needed.

In an app's repo folder you can leave it out: `pyvolt logs`, `pyvolt env list`,
`pyvolt run -- python manage.py migrate`, and `pyvolt ssh` with no server, use
the app that deploys from the folder's git remote. If that repo deploys to more
than one app (staging and production, say), pass the one you mean.

Full guide: [pyvolt.com/docs/cli](https://pyvolt.com/docs/cli/) · HTTP API:
[pyvolt.com/api/docs](https://pyvolt.com/api/docs)

## Development

```bash
uv sync
uv run pytest
```

## License

MIT. See [LICENSE](LICENSE).
