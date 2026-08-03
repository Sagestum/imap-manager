FROM debian:bookworm-slim

# Debian/Ubuntu package the tool as "1.9+git20181219-1" - a Dec 2018 snapshot
# that predates the May 2020 upstream fix for a CRLF/APPEND literal-size bug
# (github.com/nicm/fdm commit 3473690, "IMAP delivery - fix a bug in CRLF
# handling"), which caused real IMAP servers to reject deliveries with
# "3 BAD Could not parse command". Building from a pinned, newer commit
# avoids that. Bump FDM_GIT_REF if upstream ever moves again.
ARG FDM_GIT_REF=0918b78a82a789d63cebe44b7662f0a8dc603000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential autoconf automake bison pkg-config \
        libtdb-dev zlib1g-dev libssl-dev patch \
        cron util-linux \
    && rm -rf /var/lib/apt/lists/*

# fdm's deliver-imap.c has a Gmail-specific size workaround (triggered by the
# server's XYZZY capability) that sends the pre-header-insertion message size
# instead of the correctly computed one, so it undercounts the IMAP APPEND
# literal by however many bytes fdm's own "Received: by ... (fdm ...)" line
# adds - the server then reads exactly the declared (too-short) byte count
# and treats what's left over as the start of the next command, which it
# can't parse: "3 BAD Could not parse command". Confirmed against a real
# Gmail delivery. Patch removes that special case, falling back to the
# general (correct) CRLF-aware size calculation for all servers.
#
# Second patch: fdm's IMAP APPEND command never sends the optional
# date-time argument, so servers set INTERNALDATE to the delivery time
# instead of the mail's real date - delivered messages then sort/display
# with today's date in clients that go by INTERNALDATE rather than the
# Date: header. fdm already has a mailtime() helper (used for match-age
# and mail_* tags) that parses the Date: header into a time_t; this patch
# just formats that into the IMAP date-time syntax and adds it to both
# APPEND code paths (quoted-folder and literal-folder).
COPY runner/patches/fdm-xyzzy-append-size.patch /tmp/fdm-xyzzy-append-size.patch
COPY runner/patches/fdm-preserve-date.patch /tmp/fdm-preserve-date.patch

RUN git init /usr/src/fdm \
    && cd /usr/src/fdm \
    && git fetch --depth 1 https://github.com/nicm/fdm.git "$FDM_GIT_REF" \
    && git checkout FETCH_HEAD \
    && patch -p1 < /tmp/fdm-xyzzy-append-size.patch \
    && patch -p1 < /tmp/fdm-preserve-date.patch \
    && ./autogen.sh \
    && ./configure \
    && make \
    && make install \
    && cd / \
    && rm -rf /usr/src/fdm /tmp/fdm-xyzzy-append-size.patch /tmp/fdm-preserve-date.patch

# fdm faellt fuer die eigentliche Fetch-Arbeit per Privilege-Separation auf
# einen unprivilegierten Nutzer "_fdm" zurueck (compiled-in default in diesem
# Upstream-Build, anders als das alte Debian-Paket, das intern "root" nutzte).
# Ohne diesen Systemnutzer bricht jeder Lauf sofort mit "can't find user:
# _fdm" ab - verifiziert lokal, dass das Anlegen des Users das behebt.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin _fdm

COPY runner/entrypoint.sh /entrypoint.sh
COPY VERSION /VERSION
RUN chmod +x /entrypoint.sh

ENV FDM_CONFIG_DIR=/app/config \
    CRON_SCHEDULE="*/5 * * * *" \
    TRIGGER_POLL_INTERVAL=5

VOLUME ["/app/config"]

CMD ["/entrypoint.sh"]
