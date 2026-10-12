FROM certbot/certbot:latest

RUN apk add --no-cache jq openssl

COPY deploy-hook.sh /hooks/deploy-hook.sh
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh /hooks/deploy-hook.sh

ENTRYPOINT ["/entrypoint.sh"]
