uv run main.py

uv run python -m src.workers.llm_worker

uv run python -m src.workers.so_worker

uv run python -m src.workers.ocr_worker

uv run yoyo apply --database postgresql://postgres:postgres@127.0.0.1:5432/agent_service_db


docker compose -f .\docker-compose.development.yml up

docker compose -f docker-compose.development.yml up ---> linux