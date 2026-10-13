# Applies the console's entry-point rules (which ports are open, blocked networks, rate limits)
# to the host firewall with nftables. Runs on the host network with NET_ADMIN.
FROM alpine:3.20

RUN apk add --no-cache nftables

COPY entrypoint.sh /entrypoint.sh
COPY healthcheck.sh /healthcheck.sh
RUN chmod +x /entrypoint.sh /healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]
