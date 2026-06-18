FROM python:3.12-slim

# Fonts so matplotlib renders text in charts without a system display.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
# Cache mount: downloaded wheels survive across build attempts, so a retry on a
# slow/flaky link never re-fetches the large wheels (pandas/numpy/matplotlib).
# The cache is not part of the image layer, so the image stays slim without
# --no-cache-dir. Generous --timeout/--retries tolerate stalled reads.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 300 --retries 10 -r /tmp/requirements.txt

# matplotlib must never try to open a display inside the sandbox.
ENV MPLBACKEND=Agg

# Unprivileged runner; the container also runs with --user 1000:1000 at runtime.
RUN useradd -u 1000 -m runner
USER runner
WORKDIR /workspace
