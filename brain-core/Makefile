COMPOSE ?= docker-compose

.PHONY: up down logs rebuild ps shell-api shell-bot py-compile

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

rebuild:
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d --build

ps:
	$(COMPOSE) ps

shell-api:
	docker exec -it brain-api bash

shell-bot:
	docker exec -it brain-telegram-bot bash

py-compile:
	./scripts/py_compile_check.sh
