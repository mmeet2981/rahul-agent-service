
node migrate.js

add whatsapp allowed group id to .env | example: ALLOWED_GROUP_IDS=xyz@g.us

add webhook url to webhook_settings table | example: http://127.0.0.1:3034/api/whatsapp/incoming
    using following api: curl --location 'http://localhost:8080/webhooks' \
            --header 'Content-Type: application/json' \
            --data '{
                "url": "whatsapp/incoming",
                "retries": 3,
                "secret": "super_secret_webhook_key_123"
            }'


node app.js

also start llm worker in rahul-agent-service : uv run python -m src.workers.llm_worker
