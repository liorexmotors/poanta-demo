# API Service — Production Skeleton

Working name only. The public app name is not final.

## Local run

```bash
cd projects/poanta-demo
python3 -m venv .venv-api
. .venv-api/bin/activate
pip install -r services/api/requirements.txt
uvicorn services.api.app.main:app --reload --port 8000
```

Initial endpoints:
- `GET /health`
- `GET /v1/feed`
- `GET /v1/sources`
- `GET /v1/topics`
- `POST /v1/device/register`

Current mode: reads legacy `feed.json`. Next step is Postgres-backed feed versions.
