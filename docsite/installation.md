# Getting Started

Tessera ships as a single container: a Python (FastAPI) backend serving a pre-built React frontend as static assets, backed by a SQLite database on a mounted volume. There's no separate database container and no reverse proxy to stand up first.

## Prerequisites

- **Podman + podman-compose** (recommended, rootless-friendly) **or Docker + Docker Compose**
- A place for the SQLite database file to live on a persistent volume - don't run this against ephemeral/container-local storage, or your data disappears on recreate

If you intend to build/run outside a container for development, you'll also need Python 3.12+ and Node.js 20+ - see [Contributing](contributing.md).

## 1. Get the code and configure the environment

```bash
git clone https://github.com/EnthusiastDeveloper/Tessera.git
cd Tessera
cp .env.example .env
```

Edit `.env` and set, at minimum, `SECRET_KEY` (used for session signing and encrypting stored OAuth tokens). See [Configuration](configuration.md) for the full variable reference.

!!! warning "Generate a real SECRET_KEY"
    Don't ship the placeholder. Generate one with something like `openssl rand -hex 32` and keep it stable across restarts - rotating it invalidates every existing session.

## 2. Bring the container up

**With Podman (recommended):**

```bash
podman-compose up
```

**Or with Docker:**

```bash
docker-compose up
```

Either way, Tessera is served at `http://localhost:8000` (or whatever `PORT` you set in `.env`). The compose file mounts a named volume (`tessera_data`) for the SQLite database, so it survives container recreates.

A health check is built into the image (`GET /health`), which is what container orchestration should probe if you're running this under something more than plain compose.

## 3. First-run setup wizard

Tessera has **no default account and no anonymous mode** - authentication is mandatory even for a LAN-only, single-user deployment. The very first time it starts with an empty database, it does two things:

1. Generates a random, single-use **setup token** and logs it at `WARNING` level - find it with `podman logs tessera` or `docker logs tessera`.
2. Serves a one-time setup screen at the app's root URL, which is the *only* thing it will serve until an account exists.

To finish setup:

1. Open `http://localhost:8000` in a browser. You'll land on the setup screen.
2. Copy the setup token from the container logs and paste it in.
3. Choose a password (12 characters minimum, no other composition rules) and confirm it.

Once that submits, the setup endpoint is permanently closed (`410 Gone`) and the token is invalidated - there's no way to re-run setup short of wiping the database. The username is fixed as `admin`; this is a single-user app, so there's no benefit to making that configurable.

!!! tip "Lost the token before finishing setup?"
    Restart the container. A fresh token is generated on every startup while zero accounts exist - the old one was never persisted, so there's nothing stale to clean up.

## 4. Log in and configure Settings

After setup, log in with `admin` and the password you chose, then head to **Settings** and set:

- **Timezone** - defaults from the container's `TZ` env var, but confirm it's actually yours; every scheduling decision is computed in this timezone (see [Configuration](configuration.md)).
- **Active hours** - the default window(s), per day of week, that flexible tasks may be scheduled into.
- **Daily time budget** - an optional soft cap on flexible-task minutes per day.
- **External calendars** - connect Google/Outlook if you want Tessera to read your existing events as scheduling obstacles (see [Capabilities](capabilities.md)).

You're now ready to create your first task - see [Tasks & Events](tasks-and-events.md).

## Password recovery

If you're locked out, set `RESET_ADMIN_PASSWORD` in `.env` (or a mounted secret) to a new password and restart the container. It's consumed exactly once: on the restart where it's applied, Tessera resets the admin password and records that it did so, then ignores the same value on every subsequent restart (so it doesn't sit in your compose file as a standing backdoor). Resetting the password revokes every existing session.

## Updating

Pull the new image/tag (or rebuild from a newer checkout) and restart the container. The SQLite database on the mounted volume is untouched by a rebuild - back it up before any update you're unsure about, the same as you would for any single-file database.

## Building the image directly

```bash
podman build -f docker/Dockerfile -t tessera:latest .
```

The build is multi-stage: Python dependencies, then a Node.js frontend build, then a minimal Python runtime with the compiled frontend baked in - no Node or build toolchain ships in the final image.
