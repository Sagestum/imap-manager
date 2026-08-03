FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends fdm cron util-linux ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV FDM_CONFIG_DIR=/app/config \
    CRON_SCHEDULE="*/5 * * * *" \
    TRIGGER_POLL_INTERVAL=5

VOLUME ["/app/config"]

CMD ["/entrypoint.sh"]
