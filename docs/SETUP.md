# SAC — Deploy & Connect Runbook

Operational guide for the deployed service: multiple named **shared contexts**,
private/shared memory scopes, server-enforced permissions, sharing by email, and
an in-service OAuth 2.1 authorization server. Replaces the stripped-down
[`V0_MCP_PROTOTYPE.md`](V0_MCP_PROTOTYPE.md) (kept for history).

## Terminology

Users see **contexts**; the code and the older design docs say **projects**.
They are the same thing — `projects` is the internal table name, `context` is
the word in tools, URLs, and the UI. Tool parameters accept a context's **name,
slug, or id**.

## Working with contexts

Twelve MCP tools. Four manage which context you are in:

| Tool | What it does |
|---|---|
| `sac_list_contexts` | Every context available to you, and which is active |
| `sac_create_context` | Create one (you become owner) and start using it |
| `sac_use_context` | Switch. `scope="chat"` pins one conversation only |
| `sac_context_info` | Which context am I in, and what may I do here |

Eight use it: `sac_sync_context`, `sac_remember_shared`, `sac_remember_private`,
`sac_recent_changes`, `sac_get_source`, `sac_get_memory`, `sac_project_info`,
`sac_status`.

Every response carries an `active_context` block, and the compiled context leads
with `ACTIVE CONTEXT: <name> · your access: <level> · r<revision>`, so the agent
can always tell you where it is working. If no context can be determined, tools
return `needs_context_selection` with your list — the agent asks rather than
guessing.

**Sharing is never an agent tool.** Only a human can grant access, from the
website.

## Sharing a context

`/console/c/{id}` → **Share this context** → email + access level:

| Level | Can |
|---|---|
| **View** | Read shared memory. Writes are refused by the server. |
| **Edit** | Read, and publish shared + own private memory. |
| **Manage** | Edit, plus share with others and change access. |

If the address already has an account they get access immediately. If not, they
receive an invite link; signing up through it joins them automatically. Invites
expire, are single-use, bound to the address they were sent to, and revocable.
A context always keeps at least one owner.

## What the service is

One FastAPI process exposing:

```text
/mcp                         MCP v2 Streamable HTTP (Claude + ChatGPT connectors)
/v1/...                      REST mirror of the tools + sharing endpoints
/.well-known/oauth-*         OAuth 2.1 discovery (RFC 8414 / 9728)
/authorize /token /register  OAuth authorization-code + PKCE + dynamic registration
/revoke
/auth/signup /auth/login     Account creation and sign-in
/auth/verify /auth/forgot    Email verification and password reset
/auth/consent                OAuth approval for a connecting client
/auth/connections            Connected clients + revoke
/invite/{code}               Accept a shared context
/console                     Your contexts, create, connected clients
/console/c/{id}              One context: memories, members, sharing, audit
/health                      Liveness (+ user count)
/openapi.json                REST schema (servers block from SAC_PUBLIC_URL)
```

Backed by PostgreSQL on Render / SQLite locally. Identity, membership, private
vs shared scope, and permission filtering are enforced **before** any memory
reaches a model.

## Environment variables

| Var | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection (Render injects it from the blueprint DB). |
| `SAC_AUTH_MODE` | `auth` for a real deployment (default `dev` — unauthenticated, local only). |
| `SAC_PUBLIC_URL` | Public https base URL. On Render, `RENDER_EXTERNAL_URL` is used automatically; set this only to override (custom domain). |
| `SAC_BOOTSTRAP_ADMIN_EMAIL` / `SAC_BOOTSTRAP_ADMIN_PASSWORD` | Creates the first admin user on first boot if the user table is empty. |
| `SAC_ALLOWED_REDIRECT_HOSTS` | Comma list; OAuth redirect hosts allowed at registration. Defaults to the known provider hosts — it fails closed, never open. |
| `SAC_CIMD_ALLOWED_HOSTS` | Comma list; hosts allowed for ChatGPT CIMD document fetch (e.g. `chatgpt.com,openai.com`). CIMD is disabled if unset. |
| `SAC_REQUIRE_VERIFIED_EMAIL` | `1` (default) blocks unverified accounts from creating contexts or accepting shares. |
| `SAC_EMAIL_PROVIDER` | `console` (default, logs only) or `resend`. |
| `RESEND_API_KEY` / `SAC_EMAIL_FROM` | Required when the provider is `resend`. |
| `SAC_MAX_CONTEXTS_PER_USER` etc. | Quota overrides — see `app/limits.py`. |

## Deploy to Render

1. **Pre-check**: in the Render dashboard, make sure the workspace does not
   already hold an active *free* Postgres if you keep the free plan (only one is
   allowed). The blueprint here uses a paid `basic-256mb` DB by default because
   the free tier self-deletes after 30 days.
2. Push `main` (CI must be green).
3. Render → **New** → **Blueprint** → select `SamEthanMathew/Shared-Agent-Context`.
   It provisions `sac-v1-db` and the `shared-agent-context` web service from
   `render.yaml`.
4. In the web service's **Environment**, set `SAC_BOOTSTRAP_ADMIN_EMAIL` and
   `SAC_BOOTSTRAP_ADMIN_PASSWORD` (they are `sync:false`, so not in git).
5. Wait for the deploy. Record the public URL as `SAC_BASE_URL`
   (e.g. `https://shared-agent-context.onrender.com`).

### Post-deploy verification gate (run before touching any chat product)

```bash
# 1. liveness
curl -s $SAC_BASE_URL/health

# 2. unauthenticated MCP must be refused (401 + WWW-Authenticate, NOT 307)
curl -s -i -X POST $SAC_BASE_URL/mcp -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"c","version":"1"}}}' | head -1

# 3. OAuth discovery
curl -s $SAC_BASE_URL/.well-known/oauth-authorization-server | python -m json.tool
curl -s $SAC_BASE_URL/.well-known/oauth-protected-resource/mcp | python -m json.tool

# 4. full OAuth dance + authenticated tool call (needs a seeded project — see below)
SAC_BASE_URL=$SAC_BASE_URL SAC_E2E_EMAIL=<admin> SAC_E2E_PASSWORD=<pw> \
  python tests/oauth_e2e.py
```

## Bootstrap the project and second user

Use the CLI against the deployed database (Render **Shell** tab, or locally with
`DATABASE_URL` set to the external connection string):

```bash
# create the shared project (owner = admin)
python -m app.auth.cli add-project --owner <admin-email> --name "Our Project"

# add the second collaborator
python -m app.auth.cli add-user --email person-b@example.com --password <pw> --name "Person B"
python -m app.auth.cli add-member --project <project-id> --email person-b@example.com --role member
```

The admin (and any single-project member) needs no project id in tool calls —
SAC resolves it from their one membership.

## Connect Claude

1. Claude → **Settings → Connectors → Add custom connector**.
2. Name: `Shared Agent Context`; URL: `<SAC_BASE_URL>/mcp`.
3. Claude performs dynamic client registration and opens SAC's OAuth flow →
   sign in with the SAC account → approve the scopes.
4. Enable the connector in your project/chat and set the `sac_*` tools to
   "Allow always".
5. Project instructions (Person B):

   ```text
   Shared Agent Context is always-on shared project memory. While this
   connector is enabled: at the START of every turn call sac_sync_context with
   my request as `task` (and a short local_context_delta summarizing durable
   knowledge from your previous turn). Use the returned context as project
   memory. Before your final answer, call sac_remember_shared for any reusable
   decision/requirement/constraint/finding/result, or sac_remember_private for
   your own notes. Never publish secrets or personal data. Do this automatically.
   ```

## Connect ChatGPT

**Primary (direct MCP, Plus/Pro):** Settings → **Apps** → Advanced →
**Developer mode** → add a custom connector with URL `<SAC_BASE_URL>/mcp`,
authentication OAuth. ChatGPT uses CIMD (or DCR) → SAC login/consent → approve.
Paste the same instructions as above but use `sac_remember_shared` for team
knowledge and sync every turn.

**Fallback (Custom GPT + Actions):** create a Custom GPT, add an Action, import
`<SAC_BASE_URL>/openapi.json`, configure OAuth with the `/authorize` + `/token`
URLs and a client you registered. The `servers` block is present so the import
succeeds.

## Two-account acceptance test

1. **Create and share.** In `/console`, create a context. Open it → **Share this
   context** → your collaborator's email at **edit**. They receive a link.
2. **They join.** Opening the link, they sign up (or sign in), verify their
   email, and land in the context. They connect their AI client.
3. **A → B.** In ChatGPT, state a decision ("We'll use Supabase Auth and
   passkeys"). The agent calls `sac_remember_shared`. Confirm it in the console:
   memory, revision bump, audit row.
4. **B → A.** In their Claude, ask a related task. It calls `sac_sync_context`,
   receives the decision with **no copy/paste**, and publishes a constraint.
   Your next sync in ChatGPT includes it.
5. **Switching.** Create a second context, `sac_use_context` into it, and confirm
   the first context's memory does not appear — and that the agent tells you
   which context it is in.
6. **View is enforced server-side.** Change their access to **view**; their next
   `sac_remember_shared` is refused by the server, not by prompt.
7. **Private isolation.** Write a private memory; confirm the other account never
   receives it (also covered by `tests/test_permissions.py`).
8. **Revocation.** Revoke the connection in `/auth/connections`, or the person in
   the context's member list; their next call fails until re-authorized, and the
   context disappears from their list.

## Operational notes

- Treat `SAC_BASE_URL` and admin credentials as secrets.
- The service fails closed if the DB is unreachable (health check fails).
- Free Render tiers: the web service cold-starts after 15 idle minutes (pre-warm
  `/health` before a demo); the free Postgres self-deletes at 30 days — the
  blueprint uses paid plans by default to avoid both.
- V1 stores a `sensitivity` label and refuses `secret` at write time, but does
  not yet enforce per-grant sensitivity ceilings (privacy Phase 2).
