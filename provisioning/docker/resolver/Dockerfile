# A small recursive resolver for the stack (Rspamd's blocklist lookups). Internal only.
FROM alpine:3.20

RUN apk add --no-cache unbound drill

COPY unbound.conf /etc/unbound/unbound.conf

EXPOSE 53/udp 53/tcp

CMD ["unbound", "-d", "-c", "/etc/unbound/unbound.conf"]
