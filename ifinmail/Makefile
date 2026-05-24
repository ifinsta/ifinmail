.PHONY: migrate run shell collectstatic deploy provision up down build logs ps shell-api migrate-api

# --- Django targets (local development) ---
migrate:
	python manage.py migrate

run:
	python manage.py runserver 0.0.0.0:8000

shell:
	python manage.py shell

collectstatic:
	python manage.py collectstatic --noinput

deploy:
	python manage.py check --deploy
	python manage.py collectstatic --noinput
	python manage.py migrate

# --- Docker targets (provisioning) ---
DOMAIN ?= ifinsta.online
COMPOSE_BIN := $(shell if docker compose version >/dev/null 2>&1; then printf 'docker compose'; else printf 'docker-compose'; fi)
DOCKER_COMPOSE = $(COMPOSE_BIN) --env-file provisioning/.env -f provisioning/docker/docker-compose.yml

provision:
	DOMAIN="$(DOMAIN)" provisioning/scripts/provision.sh

up:
	$(DOCKER_COMPOSE) up -d

down:
	$(DOCKER_COMPOSE) down

build:
	$(DOCKER_COMPOSE) build --pull

logs:
	$(DOCKER_COMPOSE) logs -f --tail=100

ps:
	$(DOCKER_COMPOSE) ps

shell-api:
	$(DOCKER_COMPOSE) exec api python manage.py shell

migrate-api:
	$(DOCKER_COMPOSE) exec api python manage.py migrate
