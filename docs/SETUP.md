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

## Seeing what an agent was actually shown

`/console/c/{id}/snapshots` lists one row per sync: the task, the revision, how
many memories were included, how many were withheld and why, and the token
estimate against the requested budget. Opening a row shows the full manifest —
which memories went into that answer, and what was kept out.

This answers "what exactly did Claude know when it said that?" and doubles as the
privacy receipt: it reports the *count* of other members' private memories that
were withheld, without naming them.

Records are **private to the person whose agent made the call** — a snapshot
enumerates that person's private memories, so not even a context owner can read
someone else's.

## Organisations

An organisation is a group of people who share several contexts. Without one,
every context is shared person by person; with one, you grant the whole group at
once. Create one under **Organisations** in the web app.

A context belongs either to a person (the default, and what every existing
context is) or to an organisation. Moving it in is done from its **Share**
dialog, and requires being the context's owner *and* an admin of the destination
— pushing your context into someone else's group is not one person's decision.

Three sharing dials then exist side by side, and they are independent:

| Dial | Grants |
|---|---|
| **People** | A named person, at view / edit / manage. |
| **Anyone with the link** | Whoever holds the link, at view or edit. |
| **Organisation** | Everyone in the owning organisation, at view or edit. |

**Organisation access defaults to none.** Creating an organisation, adding people
to it, and moving a context into it all grant nothing on their own. Access
becomes real only when someone sets that third dial. This is deliberate: a
grouping mechanism that silently exposed existing memory the moment it was used
would be unsafe to adopt.

**It can never grant *manage*** — the same rule as share links, for the same
reason. Manage carries the right to re-share, and neither a link nor group
membership should be able to pass that on.

**Administering an organisation is not the same as reading its contexts.** An
organisation admin can see which contexts belong to the group and how each is
shared, which is what administering a group requires. Reading one still needs the
organisation dial to allow it, or an invitation of their own.

### How access is stored, and why it matters

Organisation access is **materialised into ordinary membership rows**, tagged
`source='org'`, rather than checked as a second permission path. The permission
boundary (`_visible()` and `resolve_identity`) never learns about organisations at
all, so every existing query, test, and isolation guarantee keeps working
unchanged, and an org-derived member is indistinguishable from an invited one at
read time.

The rule that follows is worth knowing as a user: **an explicit invitation
outranks organisation access.** Removing someone from an organisation revokes
only what the organisation gave them — a context they were invited to
individually stays theirs. That is what anyone would expect, and it is the
behaviour that fails safe when two people are managing access independently.

## How long data is kept

A `sac-reaper` cron job (`scripts/reaper.py`, daily) applies retention. It is a
separate job rather than a thread in the web service on purpose: a reaper inside
the web process dies with every deploy and runs twice as soon as there are two
instances. Run `python scripts/reaper.py --dry-run` to see what a pass would
remove without removing it.

> **A new service in `render.yaml` does not appear by itself.** Render creates
> services from a blueprint only when the blueprint is applied, and this
> deployment's services were created individually rather than from one — the
> workspace has no blueprint registered at all. So an ordinary `git push`
> redeploys what already exists and silently ignores anything newly declared
> here. The reaper was therefore created directly against the Render API; the
> declaration below is kept as the source of truth for its configuration. If you
> ever adopt blueprints, apply this file once and Render will adopt the existing
> services.

| Data | Kept |
|---|---|
| **Memory** (shared and private) | **Indefinitely.** Retention never touches the product's actual content. |
| **Audit trail** — who shared what with whom, access changes, archiving | **Indefinitely.** Small, append-only, and the record you need to answer a question about the past. |
| **Sync records** — what each agent was shown per turn | **90 days** (`SAC_RETENTION_DAYS_SNAPSHOTS`). |
| Expired OAuth transactions, codes, access tokens, sessions, email tokens | Deleted once expired. |
| Revoked refresh tokens | 30 days, so "when did this connection lose access" stays answerable. |
| Rate-limit counters | 1 day. |
| Client registrations nobody completed | 1 day. `/register` needs no credentials, so rate limiting caps how *fast* rows arrive without bounding how many accumulate. A registration that produced a connection is kept indefinitely — including a revoked one, since the audit trail refers to it. |

The 90-day window on sync records is a privacy decision, not only a storage one.
Each record enumerates the memories fed to one person's agent — including their
private ones — so keeping them forever accumulates a detailed history of what
each person's assistant saw. Ninety days is long enough to answer "what exactly
did Claude know when it said that", and short enough that the record does not
become an asset in its own right.

## Archiving a context

An owner can archive a context from its console page. It disappears from every
listing, can no longer be resolved by name or id, and any client bindings
pointing at it are cleared, so agents stop seeing it immediately.

Memory is retained — archiving is a projection, not a deletion. Restore it from
the **Archived** section on `/console` and everything comes back at the same
revision.

## Sharing a context

Open the context in the web app and press **Share**. There are up to three
independent dials — per person and by link, as in Google Docs, plus the
organisation dial when the context belongs to one (see *Organisations* above).

**Per person** — invite by email at a level:

| Level | Can |
|---|---|
| **View** | Read shared memory. Writes are refused by the server. |
| **Edit** | Read, and publish shared + own private memory. |
| **Manage** | Edit, plus share with others and change access. |

If the address already has a **verified** account they get access immediately.
Otherwise they receive an invite link; signing up through it joins them. An
unverified account is deliberately treated as no account — otherwise anyone could
register someone else's address and silently collect contexts shared to it.
Invites expire, are single-use, bound to the address they were sent to, and
revocable. A context always keeps at least one owner.

**General access** — "anyone with the link":

| Setting | Meaning |
|---|---|
| **Restricted** | Only the people invited above. The default. |
| **Anyone with the link can view** | Read-only for whoever holds the link. |
| **Anyone with the link can edit** | Read and publish for whoever holds the link. |

A link can never grant **manage**. Manage carries the right to re-share, and a
link that could pass that on would propagate access no human chose — so "who can
share this" stays a per-person decision made by a named owner or manager. Only
owners and managers can see the link itself, because holding it is equivalent to
being able to share. **Generate a new link** invalidates every copy already
circulating; people who already joined keep their access.

Turning link sharing off stops new joins and does not evict anyone.

## What the service is

One FastAPI process exposing:

```text
/app                         The web app (React). Contexts, sharing, AI clients.
/mcp                         MCP v2 Streamable HTTP (Claude + ChatGPT connectors)
/v1/...                      REST API. Bearer tokens (agents) or session cookie (app)
/.well-known/oauth-*         OAuth 2.1 discovery (RFC 8414 / 9728)
/authorize /token /register  OAuth authorization-code + PKCE + dynamic registration
/revoke
/auth/signup /auth/login     Account creation and sign-in
/auth/sso/{provider}/...     Sign in with Google or GitHub (when configured)
/auth/verify /auth/forgot    Email verification and password reset
/auth/consent                OAuth approval for a connecting client
/auth/connections            Connected clients + revoke
/invite/{code}               Accept a share sent to your email
/c/{token}                   Join via an "anyone with the link" share
/console                     Fallback server-rendered console
/console/c/{id}/snapshots    What your agents were actually shown (per sync)
/health                      Liveness (+ user count)
/openapi.json                REST schema (servers block from SAC_PUBLIC_URL)
```

`/app` is the product surface; `/console` is kept as a no-JavaScript fallback and
links across to the app.

### The web app

Source in `web/`, built with Vite. **The build output is committed** to
`app/static/app`, so deploying this Python service needs no Node toolchain. If you
change anything under `web/src`, run `npm run build` in `web/` and commit the
result — CI rebuilds and fails if the two have drifted. See `web/README.md`.

The app authenticates with the ordinary login cookie rather than a token. Because
a cookie is ambient, `/v1` requires a CSRF token on every write: the `sac_csrf`
cookie echoed back in an `X-SAC-CSRF` header. Bearer-token callers (the AI
clients) are unaffected.

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
| `SAC_GOOGLE_CLIENT_ID` / `SAC_GOOGLE_CLIENT_SECRET` | Enables "Continue with Google". Absent → the button is not shown. |
| `SAC_GITHUB_CLIENT_ID` / `SAC_GITHUB_CLIENT_SECRET` | Enables "Continue with GitHub". |
| `SAC_SECRET_KEY` | Signs CSRF tokens. Optional: unset means a per-process key, so tokens stop validating across a restart and the app quietly reissues one. Set it to avoid that. |
| `SAC_DB_POOL_SIZE` / `SAC_DB_MAX_OVERFLOW` | Connections per process (default 10 + 10). `app/main.py` caps the worker-thread pool to the same total, so the process never accepts more concurrency than the database can serve. Their sum × instances, plus the reaper, must stay under the Postgres plan's `max_connections`. |
| `SAC_RETENTION_DAYS_SNAPSHOTS` | How long sync records are kept (default 90). See *How long data is kept*. |
| `SAC_COMPILE_CANDIDATE_LIMIT` | Live memories one sync may rank (default 750). Past this a sync considers the most recent slice and reports `candidates_truncated`. |
| `SAC_MAX_CONTEXTS_PER_USER` etc. | Quota overrides — see `app/limits.py`. |

### Sign-in with Google or GitHub

Neither Anthropic nor OpenAI offers consumer OAuth to third-party apps, so
"sign in with your Claude account" cannot be built. Google and GitHub cover the
actual need — not inventing another password — and the account behind a ChatGPT
or Claude login is usually a Google one.

To enable Google: create an OAuth client at
`console.cloud.google.com` → APIs & Services → Credentials → *OAuth client ID*
(type: Web application), with the authorized redirect URI:

```text
<SAC_BASE_URL>/auth/sso/google/callback
```

Then set `SAC_GOOGLE_CLIENT_ID` and `SAC_GOOGLE_CLIENT_SECRET`. GitHub is the
same shape (Settings → Developer settings → OAuth Apps), callback
`<SAC_BASE_URL>/auth/sso/github/callback`.

When the provider says it verified the address, the account is marked verified
here too — a second verification email would ask the user to prove the same fact
twice. When it does not, the account stays unverified and, if that address already
has an account, the sign-in is **refused rather than linked**: otherwise a
provider that lets someone claim an unverified address becomes a way into
another user's contexts.

### Connecting a client as a brand-new user

A person who has never visited the site can start from their AI client: add the
connector, and the OAuth flow lands them on sign-in with a **Create one** link
that carries the pending connection through signup and back to consent. They
finish inside the client they started in.

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
