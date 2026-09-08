# birdlistener (laptop CLI)

The one tool you run on your own computer to set up and look after a
bird-listener install. Stdlib-only Python 3.10+.

```bash
uv tool install ./cli          # or: pipx install ./cli
birdlistener flash             # write the window node's SD card (asks a few questions)
birdlistener flash --node wall # write the wall node's card (asks nothing new)
birdlistener doctor            # health of both Pis
birdlistener art               # build the bird art and put it on the wall node
birdlistener update            # pull the latest code onto both Pis
```

Every prompt has a flag (`birdlistener flash --help`), so an agent can drive
it end to end; `--dry-run` shows exactly what would happen. What it remembers
about your install (hostnames, generated passwords, location) lives in
`~/.config/bird-listener/site.json`.
