# Osmos web app

React + Vite front end for Osmos, served by FastAPI at `/app`.

## Why the build output is committed

`npm run build` writes to `../app/static/app`, and **that directory is committed
to git**. This is deliberate: the deploy target is a Python service, and keeping
the built assets in the repo means Render needs no Node toolchain, no
`npm install` on the critical path, and no second build step that can fail
independently of the tests.

The cost is that a source change is not live until someone rebuilds. So:

> **If you change anything in `web/src`, run `npm run build` and commit the
> result alongside it.** CI checks this and fails if the two drift.

## Working on it

```bash
npm install

# Terminal 1 — the API
cd .. && SAC_AUTH_MODE=dev uvicorn app.main:app --reload

# Terminal 2 — the front end, proxying /v1 and /auth to uvicorn
npm run dev
```

Vite serves on :5173 and proxies the API, so the session cookie works exactly as
it does in production. Sign in through `/auth/login` first.

```bash
npm run build      # writes ../app/static/app — commit this
```

## How it authenticates

There is no token in the front end. The browser holds the `sac_session` cookie
from `/auth/login`, and `/v1` accepts it (see `app/browser.py`). Because a cookie
is ambient, every mutating request echoes the `sac_csrf` cookie back in an
`X-SAC-CSRF` header; `src/api.js` does this centrally, so individual calls don't
have to think about it.

A 401 anywhere redirects to `/auth/login?next=…` and returns here afterwards.

## Layout

| File | What it is |
|---|---|
| `src/api.js` | The `/v1` client. The only place `fetch` and CSRF live. |
| `src/router.jsx` | ~40 lines over the History API. Three routes don't justify a dependency. |
| `src/App.jsx` | Shell, top bar, context switcher, create-context dialog. |
| `src/ShareDialog.jsx` | The two sharing dials: link access, and per-person roles. |
| `src/views/` | Contexts list, one context (memory/people/activity/what-AI-saw), AI clients. |
| `src/ui.css` | The design system, built on `website/tokens.json`. |

## Design rule

From `website/AI_BRAND_CONTEXT.md`:

> The interface is calm and neutral; colour appears when knowledge moves.

So the chrome is ink and mist, and the flow gradient is reserved for the few
places where something actually moved: the live-context marker, and a memory
that arrived from someone else's agent. If the gradient starts appearing on
ordinary buttons, that rule has been broken.
