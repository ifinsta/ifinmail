# CalDAV / CardDAV (Radicale): calendars and contacts for the same mailboxes, behind nginx at /dav/.
# Passwords are checked by Dovecot, so a mailbox password works here too and nothing is stored twice.
FROM python:3.12-slim

RUN pip install --no-cache-dir "radicale==3.8.3" \
    && groupadd -g 5001 radicale \
    && useradd -g radicale -u 5001 -d /var/lib/radicale -s /usr/sbin/nologin radicale \
    && mkdir -p /var/lib/radicale && chown radicale:radicale /var/lib/radicale

COPY config /etc/radicale/config

USER radicale
VOLUME ["/var/lib/radicale"]
EXPOSE 5232
CMD ["python", "-m", "radicale", "--config", "/etc/radicale/config"]
