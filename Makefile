.PHONY: up down migrate test worker logs shell

up:
	docker-compose up --build -d

down:
	docker-compose down

migrate:
	docker-compose exec api alembic upgrade head

migrate-local:
	alembic upgrade head

worker:
	celery -A app.workers.celery_app worker --loglevel=info --concurrency=2

test:
	pytest tests/unit/ -v --cov=app --cov-report=term-missing

test-integration:
	pytest tests/integration/ -v

logs:
	docker-compose logs -f api worker

shell:
	docker-compose exec api bash

flower:
	celery -A app.workers.celery_app flower
