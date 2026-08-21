FROM debian:trixie-slim

# imapsync gibt es nicht als Debian-Paket (2011 wegen einer Lizenzdiskussion aus Debian entfernt,
# siehe tracker.debian.org/pkg/imapsync). Wie zuvor bei fdm wird das Skript von einem gepinnten
# Commit installiert; die CPAN-Abhaengigkeiten kommen als Debian-Pakete. Liste uebernommen aus dem
# offiziellen Dockerfile des Projekts (github.com/imapsync/imapsync/INSTALL.d/Dockerfile), minus
# der Pakete, die nur fuers eingebaute Web-Formular (servimapsync) oder PAR-Packaging noetig sind.
# Debian-Basis bewusst trixie statt bookworm: libcrypt-openssl-pkcs12-perl wurde 2022 wegen eines
# OpenSSL-3.0-Build-Fehlers aus bookworm entfernt (existiert nur noch in trixie/unstable).
ARG IMAPSYNC_GIT_REF=93654c6025ff7814f983ab74dd300f9bed9282d9

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libauthen-ntlm-perl \
        libcrypt-openssl-pkcs12-perl \
        libcrypt-openssl-rsa-perl \
        libdata-uniqid-perl \
        libemail-address-perl \
        libencode-imaputf7-perl \
        libfile-copy-recursive-perl \
        libfile-tail-perl \
        libio-compress-perl \
        libio-socket-ssl-perl \
        libio-socket-inet6-perl \
        libio-tee-perl \
        libhtml-parser-perl \
        libjson-webtoken-perl \
        libmail-imapclient-perl \
        libnet-dns-perl \
        libnet-server-perl \
        libparse-recdescent-perl \
        libproc-processtable-perl \
        libreadonly-perl \
        libregexp-common-perl \
        libsys-meminfo-perl \
        libterm-readkey-perl \
        libtest-deep-perl \
        libtest-mockobject-perl \
        libtest-pod-perl \
        libunicode-string-perl \
        liburi-perl \
        libwww-perl \
        procps \
        python3 \
        ca-certificates wget cron util-linux \
    && wget -O /usr/local/bin/imapsync \
        "https://raw.githubusercontent.com/imapsync/imapsync/${IMAPSYNC_GIT_REF}/imapsync" \
    && chmod +x /usr/local/bin/imapsync \
    && imapsync --version \
    && python3 -c 'import sqlite3' \
    && rm -rf /var/lib/apt/lists/*
# --version statt --tests: die eingebaute Testsuite prueft u.a. Live-IPv6-Konnektivitaet zu
# test1ipv6.lamiral.info und den oeffentlichen Release-Stand - beides im isolierten Docker-Build
# nicht gegeben (kein IPv6, gepinnter Dev-Commit statt Release). --version laedt trotzdem alle
# Perl-Module per "use" und deckt damit fehlende CPAN-Abhaengigkeiten weiterhin auf.

COPY imapsync_gen.py /app/imapsync_gen.py
COPY stats_store.py /app/stats_store.py
COPY mail_filter.py /app/mail_filter.py
COPY runner/run_sync.py /app/run_sync.py
COPY runner/entrypoint.sh /entrypoint.sh
COPY VERSION /VERSION
RUN chmod +x /entrypoint.sh

ENV FDM_CONFIG_DIR=/app/config \
    CRON_SCHEDULE="*/5 * * * *" \
    TRIGGER_POLL_INTERVAL=5

VOLUME ["/app/config"]

CMD ["/entrypoint.sh"]
