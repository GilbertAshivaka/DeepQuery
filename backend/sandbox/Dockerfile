# Source a modern Node runtime from the official image (avoids Debian's heavy, fragile
# node-* package tree + ancient npm). Bookworm to match the Python base's glibc.
FROM node:20-bookworm-slim AS node

FROM python:3.12-slim-bookworm

# ── Fonts ── matplotlib text + nicer document typography (Liberation = Arial/Times-
# compatible) + Noto Color Emoji for emoji in any format.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# ── Node runtime (copied, not apt-installed) ──
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

# ── Python libraries (spreadsheets, charts, PDF) ──
COPY requirements.txt /tmp/requirements.txt
# Cache mount: downloaded wheels survive build retries on a slow/flaky link.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 300 --retries 10 -r /tmp/requirements.txt

# ── Node libraries (design-rich docx & pptx) ──
# Installed to a fixed prefix; NODE_PATH lets a generated script `require()` them by name.
# npm cache mount survives build retries (sharp pulls a prebuilt libvips binary).
COPY package.json /opt/dq-node/package.json
RUN --mount=type=cache,target=/root/.npm \
    npm install --prefix /opt/dq-node --omit=dev --no-audit --no-fund --fetch-timeout=600000
ENV NODE_PATH=/opt/dq-node/node_modules

# matplotlib must never try to open a display inside the sandbox.
ENV MPLBACKEND=Agg

# Unprivileged runner; the container also runs with --user 1000:1000 at runtime.
RUN useradd -u 1000 -m runner
USER runner
WORKDIR /workspace
