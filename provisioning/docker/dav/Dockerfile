# CalDAV / CardDAV (Radicale): calendars and contacts for the same mailboxes, behind nginx at /dav/.
# directory-sync.py mirrors the console's contact directory (names and photos) into a read-only
# address book in every mailbox's home.
# Passwords are checked by Dovecot, so a mailbox password works here too and nothing is stored twice.
FROM python:3.12-slim

RUN pip install --no-cache-dir "radicale==3.8.3" \
    && groupadd -g 5001 radicale \
    && useradd -g radicale -u 5001 -d /var/lib/radicale -s /usr/sbin/nologin radicale \
    && mkdir -p /var/lib/radicale && chown radicale:radicale /var/lib/radicale

COPY config /etc/radicale/config
COPY rights /etc/radicale/rights
COPY directory-sync.py entrypoint.sh /usr/local/bin/

USER radicale
VOLUME ["/var/lib/radicale"]
EXPOSE 5232
CMD ["/usr/local/bin/entrypoint.sh"]
