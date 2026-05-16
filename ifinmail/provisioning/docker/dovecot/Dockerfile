# Dovecot container for ifinmail
FROM ubuntu:24.04

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    dovecot-core \
    dovecot-imapd \
    dovecot-lmtpd \
    dovecot-pgsql \
    dovecot-sieve \
    dovecot-managesieved \
    && rm -rf /var/lib/apt/lists/*

# Create vmail user (UID 5000, GID 5000 — must match postfix)
RUN groupadd -g 5000 vmail \
    && useradd -g vmail -u 5000 -d /var/mail/vhosts -s /usr/sbin/nologin vmail \
    && mkdir -p /var/mail/vhosts \
    && chown -R vmail:vmail /var/mail/vhosts

# Copy configuration
COPY dovecot.conf /etc/dovecot/dovecot.conf
COPY dovecot-sql.conf.ext /etc/dovecot/dovecot-sql.conf.ext
COPY conf.d/ /etc/dovecot/conf.d/
COPY sieve/ /etc/dovecot/sieve/

RUN chmod 640 /etc/dovecot/dovecot-sql.conf.ext \
    && chown root:dovecot /etc/dovecot/dovecot-sql.conf.ext \
    && mkdir -p /var/run/dovecot \
    && chown root:root /var/run/dovecot \
    && chmod 755 /var/run/dovecot \
    && mkdir -p /etc/dovecot/sieve/before.d /etc/dovecot/sieve/after.d

EXPOSE 143 993

CMD ["dovecot", "-F"]
