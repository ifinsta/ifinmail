# Postfix container for ifinmail
FROM ubuntu:24.04

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    postfix \
    postfix-pgsql \
    sasl2-bin \
    && rm -rf /var/lib/apt/lists/*

# Create vmail user (UID 5000, GID 5000 — must match dovecot)
RUN groupadd -g 5000 vmail \
    && useradd -g vmail -u 5000 -d /var/mail/vhosts -s /usr/sbin/nologin vmail

# Copy configuration
COPY main.cf /etc/postfix/main.cf
COPY master.cf /etc/postfix/master.cf
COPY pgsql/ /etc/postfix/pgsql/

RUN chmod 640 /etc/postfix/pgsql/*.cf \
    && chown root:postfix /etc/postfix/pgsql/*.cf \
    && mkdir -p /var/spool/postfix \
    && chown -R postfix:postfix /var/spool/postfix \
    && mkdir -p /var/mail/vhosts

EXPOSE 25 465 587

CMD ["postfix", "start-fg"]
