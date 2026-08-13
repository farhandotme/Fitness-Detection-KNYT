# Competition Backend

Node/Bun + TypeScript competition authority for the real-time exercise
competition platform. This service owns **events, rooms, participants,
rounds, live ranking and final results**. It never touches a camera frame -
that stays entirely inside the existing `detection-backend` (FastAPI +
OpenCV + MediaPipe), which the React frontend continues to talk to directly
exactly as it does today.

```
React  ──REST + Socket.IO──▶  competition-backend (this service)
  │                                 │        │
  └────WebSocket (unchanged)──▶ FastAPI   MongoDB / Redis
                              (pose/reps)
```

## Stack

Node.js (Bun runtime) · TypeScript · Express · Socket.IO · MongoDB
(Mongoose) · Redis (ioredis) · Zod · Helmet · CORS · Pino structured logging.

## Responsibilities (and non-responsibilities)

- Owns: event catalog, room/participant lifecycle, the 5-participant cap,
  round/break/countdown timing, the official leaderboard, final results.
- Does **not**: run OpenCV/MediaPipe, decide exercise form quality, or trust
  any score, rank, or winner value sent by a client. The frontend only ever
  displays what this service broadcasts.

## Getting started

```bash
cp .env.example .env        # then edit MONGODB_URI / REDIS_URL if needed
bun install
bun run seed                # creates a few sample live events
bun run dev                 # http://localhost:4000
```

Requires a MongoDB instance and a Redis instance reachable at the URLs in
`.env`. For local development the quickest path is:

```bash
docker run -d -p 27017:27017 --name comp-mongo mongo:7
docker run -d -p 6379:6379 --name comp-redis redis:7
```

## Data model

- **Redis** — live, high-churn state only: room membership (with an atomic
  Lua script enforcing the participant cap so two people can never take the
  last slot at once), and the live per-round score hash the leaderboard is
  computed from. Keys expire a few hours after room creation.
- **MongoDB** — permanent history: `events`, and `competitions` (one document
  per room, holding participants, per-round scores, and final results). No
  camera frames or per-frame pose data are ever written here.

## Synchronized timing

Every phase change (countdown, round start, round end, break) is driven by
this process and broadcast as an **absolute server timestamp**
(`countdownEndAt`, `roundStartAt`, `roundEndAt`, `breakEndAt`, plus
`serverNow` for clients to correct for clock drift) via the `room:state`
Socket.IO event. Clients render their own countdown against that timestamp
instead of trusting a bare "start now" message, so everyone begins together
regardless of individual latency.

## Socket.IO contract

Client → server: `competition:join`, `competition:reconnect`,
`score:update`, `competition:leave`.
Server → client: `competition:joined`, `competition:reconnected`,
`room:state` (full snapshot, sent on every state change),
`competition:completed`, `error`.

See `src/types/index.ts` for the exact payload shapes shared conceptually
with the frontend's `src/types/competition.ts`.

## REST API

- `GET /api/events` — live events a visitor can join.
- `GET /api/events/:id` — event details for the join screen.
- `GET /health` — liveness/readiness probe (checks Mongo + Redis).
- `POST /api/admin/auth/register` — create an admin account. Body:
  `{ username, password, signupCode }`. `signupCode` must match
  `ADMIN_SIGNUP_CODE` in `.env` — this is the one thing gating who can become
  an admin, since v1 otherwise has no user accounts at all. Returns
  `{ token, username }`.
- `POST /api/admin/auth/login` — `{ username, password }` → `{ token, username }`.
- `GET /api/admin/me`, `GET/POST/PATCH /api/admin/events`,
  `POST /api/admin/events/:id/status` — event management. All require
  `Authorization: Bearer <token>` from register/login above.
- `GET /api/admin/stats` — dashboard summary counts (live rooms, players
  online now, live events, completed competitions).
- `GET /api/admin/competitions/live` — every competition room currently in
  progress (any status other than `COMPLETED`/`ABANDONED`), across all
  events, for the admin "live now" board.
- `GET /api/admin/competitions/:id` — full live snapshot of one room
  (participants, leaderboard, round/timer state) - same shape a participant
  gets over Socket.IO, used for the admin spectator view's first paint.

## Watching a live competition as admin

Beyond the REST snapshot above, the admin dashboard's "Watch live" view stays
live via a dedicated Socket.IO event: emit `admin:spectate` with
`{ competitionId, adminToken }` (the JWT from login/register). The server
verifies the token, joins that socket to the room's Socket.IO channel, and
from then on the admin receives the exact same `room:state` broadcasts every
participant does. Critically, the admin is **never added to the
competition's participant list** - watching doesn't occupy one of the room's
5 seats, doesn't appear in the leaderboard, and can't submit scores (there's
no `score:update` path available from a spectate-only connection).

## Admin accounts

Event creation used to be gated by a single shared `x-admin-api-key`. It's
now backed by real (if intentionally minimal) admin accounts:
`AdminUserModel` stores a bcrypt password hash, login/register issue a
12-hour JWT (`JWT_SECRET` in `.env`), and every `/api/admin/*` route checks
that token. Use the frontend's `/admin/login` page (Register tab) with the
`ADMIN_SIGNUP_CODE` from your `.env` to create your first admin login, then
create events from `/admin`.

## Duplicate-enrollment prevention

The frontend has no login, so participant identity is normally just
"whatever `displayName` + freshly generated `participantId`/`participantToken`
the browser was handed on join" (spec section 13). Nothing about that alone
stops one person from re-opening the join page and clicking "Join" again,
occupying two (or more) of a room's 5 seats.

To close that gap without adding real user accounts, the frontend generates
and persists a random device id per browser (`src/lib/deviceId.ts`,
localStorage-backed) and sends it with every `competition:join`. The backend
hashes it and checks: does this device already hold an active seat (any
room for this event that isn't `COMPLETED`/`ABANDONED`)? If so, it rotates
that seat's credential and reattaches the caller to it instead of creating a
new participant — so re-clicking "Join" is idempotent rather than
seat-consuming. Like everything else about identity here, this is a
best-effort, no-login-required control (clearing storage or using a
different browser bypasses it) — real accounts would be the way to make it
airtight, which is out of scope for v1 per the spec.

## Production

See `../PRODUCTION.md` at the repo root for the full deployment checklist
(secrets, TLS, rate limiting, Docker, etc). In short: this service refuses to
boot in `NODE_ENV=production` with placeholder secrets, rate-limits
`/api/admin/auth/*`, and ships with a hardened non-root Dockerfile.

## Known v1 scope limits

- Round/break timers live in this process's memory, matching the "first
  version, single Node backend" scope in the spec. If the process restarts
  mid-round, in-flight timers are lost (Mongo/Redis state is unaffected).
  Moving to a distributed scheduler is the natural next step if this needs
  to run as more than one instance.
- Admin auth is a shared API key, not a login system, matching "no login for
  the current version".
