# TODO(item 3): consider pinning base image by immutable digest for stricter reproducibility.
FROM python:3.12.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Install runtime dependencies only.
COPY requirements.txt ./
# TODO(item 3): consider pinning or removing `pip install --upgrade pip` for stricter reproducibility.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy runtime assets required for CLI and migrations.
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src

# Create local data directories and a non-root runtime user.
RUN mkdir -p /app/data/warehouse /app/data/bronze /app/data/gold \
    && groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app \
    # TODO(item 1): tighten /app/data permissions to least privilege while preserving bind-mount/UID-GID workaround
    # (narrower mode/group/setgid, documented ETL_UID/GID mapping, host chown/prep, named volume, or runtime ownership handling if justified).
    # Validation showed custom ETL_UID/GID on a fresh host dir can still fail if host dir is not writable; chmod alone is insufficient.
    && chmod -R a+rwx /app/data

USER appuser

# Default: apply migrations then run the full ETL. Override the command to run
# other CLI operations (for example validate or run-all --export-csv).
CMD ["sh", "-c", "python -m violence_etl.cli init-db && python -m violence_etl.cli run-all"]
