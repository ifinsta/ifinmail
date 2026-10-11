# Authoritative DNS (Knot DNS): serves the zones the console publishes and signs them with DNSSEC.
FROM debian:bookworm-slim

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends knot knot-dnsutils \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/knot /var/lib/knot /runtime \
    && chown -R knot:knot /run/knot /var/lib/knot

COPY knot.conf /etc/knot/knot.conf
COPY entrypoint.sh /usr/local/bin/ifinmail-dns
RUN chmod +x /usr/local/bin/ifinmail-dns

EXPOSE 53/udp 53/tcp
VOLUME ["/var/lib/knot"]
ENTRYPOINT ["/usr/local/bin/ifinmail-dns"]
