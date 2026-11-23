# 5G Measurement Dashboard — frontend

React + Vite + TypeScript SPA for the [`5G-Measurement-Backend`](..) dashboard: the web UI for the
data the backend receives from the field devices of
[`5G-Measurement-Software`](https://github.com/tguttzeit/5G-Measurement-Software).

## Stack

- **React** + **Vite**, **TypeScript**.
- **React Router** for client-side routing.
- Dependency management via **npm**.

## Local development setup

1. Install dependencies:

   ```sh
   npm install
   ```

2. Run the dev server:

   ```sh
   npm run dev
   ```

   Requests to `/api/*` are proxied to a local FastAPI backend
   (`uv run uvicorn app.main:app --reload` from the repo root, see the root README) running on
   `http://localhost:8000`.

## Build, lint and test

```sh
npm run build
npm run lint
npm test
```

## Pages

Public pages need no login; the others redirect to `/login`, and the admin and remote
configuration pages additionally need a superuser account.

- **Map** (`/map`, also `/`) — street map with heatmap or points of measurement data, scoped to one
  campaign. Public; guests see aggregates and points without device ID and time.
- **Mission Status** (`/status`) — heartbeat visualization for active and recent missions.
- **Runs** (`/runs`) — list and edit measurement runs.
- **Testing** (`/testing/visualization`) — results of manual integration tests.
- **Remote Configuration** (`/remote-configuration`, superuser) — device config overrides and
  one-shot commands.
- **Settings** (`/settings`) — application settings.
- **Change password** (`/change-password`).
- **Admin** (`/admin/users`, `/admin/campaigns`, superuser) — user and campaign management.
