#!/usr/bin/env bash
# Build the habit_tracker_api image behind the corporate (Zscaler) TLS proxy.
#
# The Dockerfile needs the Zscaler CA bundle inside the build context, but
# certificates must NEVER be committed to this repo. This script stages the
# bundle from outside the repo, builds the image, and always removes the
# transient copy afterwards (even on failure).
#
# Override the bundle location with: ZSCALER_CA_PATH=/path/to/bundle.pem ./build.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZSCALER_CA_PATH="${ZSCALER_CA_PATH:-$HOME/code/certs/zscaler-ca.pem}"
STAGED_CA="$REPO_DIR/zscaler-ca.pem"

# Defense in depth: refuse to stage a cert unless .gitignore shields it.
for pattern in 'certs/' '*.pem' '*.crt' '*.cer'; do
    if ! grep -qxF "$pattern" "$REPO_DIR/.gitignore"; then
        echo "ERROR: .gitignore is missing the '$pattern' entry." >&2
        echo "Refusing to copy a certificate into the repo without it." >&2
        exit 1
    fi
done

if [[ ! -f "$ZSCALER_CA_PATH" ]]; then
    echo "ERROR: CA bundle not found at $ZSCALER_CA_PATH" >&2
    echo "Set ZSCALER_CA_PATH to the bundle location and re-run." >&2
    exit 1
fi

cleanup() {
    rm -f "$STAGED_CA"
}
trap cleanup EXIT

cp "$ZSCALER_CA_PATH" "$STAGED_CA"

podman compose -f "$REPO_DIR/docker-compose.yml" build api
