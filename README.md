# Habit Tracker API

Install dependencies and run in vscode using launch.json

```bash
uv sync
```

or build and run using Podman:

```bash
podman build  -f Dockerfile -t habit-tracker-api:latest .
podman run -p 8080:8080 habit-tracker-api:latest
```
