# 5G Measurement Backend

Backend server for [`5G-Measurement-Software`](https://github.com/tguttzeit/5G-Measurement-Software):
it receives the field devices' heartbeats and measurement/latency uploads, serves the dashboard
and dispatches remote config overrides and commands back to the devices.

Built with **FastAPI**, **SQLAlchemy 2.0** and **Alembic** on **Postgres**; the dashboard in
`frontend/` is a Vite + React + TypeScript app.

## Documentation

Configuration, device registration, deployment, the flent server and local testing are documented
on the documentation site of the backend server:
[`https://bosdra.net.tha.de/docs/`](https://bosdra.net.tha.de/docs/)
(German: [`/docs/de/`](https://bosdra.net.tha.de/docs/de/), English:
[`/docs/en/`](https://bosdra.net.tha.de/docs/en/)).

The API reference is generated from the application's OpenAPI schema and published with the
documentation site under `/docs/en/backend/dev/api/` (the schema itself at
`/docs/en/backend/dev/api/openapi.json`). The application serves no Swagger UI, ReDoc or schema of its own; `/api/docs`, `/api/redoc` and
`/api/openapi.json` redirect there. The summaries and descriptions of the endpoints and schemas
in `app/` are the reference's only source.
