# Tessera

**Self-hosted task scheduling that respects the real shape of your day.**

Tessera fits your flexible tasks into the gaps left by fixed commitments, deadlines, priorities, and dependencies - inside a daily capacity you set, not just wherever a slot happens to be free.

📖 **[Read the full guide](https://enthusiastdeveloper.github.io/Tessera/)** - installation, configuration, capabilities, task types, the scheduling algorithm, and troubleshooting.

## Quick start

```bash
git clone https://github.com/EnthusiastDeveloper/Tessera.git
cd Tessera
cp .env.example .env   # set SECRET_KEY at minimum
podman-compose up      # or: docker-compose up
```

Open `http://localhost:8000` and follow the first-run setup wizard (setup token is printed in the container logs). See [Getting Started](https://enthusiastdeveloper.github.io/Tessera/installation/) for the full walkthrough, including local (non-container) development setup.

## Documentation

- **[User guide](https://enthusiastdeveloper.github.io/Tessera/)** - hosted docs for installing, configuring, and using Tessera (source: [`docsite/`](docsite/))
- **[Design Document](docs/design-doc.md)** - authoritative product specification
- **[Architecture Plan](docs/architecture-plan.md)** - how the system is structured and built
- **[Implementation Plan](docs/implementation-plan.md)** - staged build sequence, gates, and current progress
- **[Implementation-Readiness Review #2](docs/implementation-readiness-review-2.md)** - findings register and decision log behind the design/architecture docs
- **[CLAUDE.md](CLAUDE.md)** - guidance for Claude Code when working in this repository

## Contributing

This is a single-developer POC. If you're picking up work, start with the [Contributing guide](https://enthusiastdeveloper.github.io/Tessera/contributing/) - it covers dev setup, testing, architecture layering, and branching/CI conventions.

## License

[See LICENSE file](LICENSE)
