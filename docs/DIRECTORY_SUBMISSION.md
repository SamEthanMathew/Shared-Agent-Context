# Directory submission pack

Everything the Anthropic and OpenAI review portals ask for, drafted and ready to
paste. Field lengths are checked by `tests/test_submission_pack.py`, because both
portals silently truncate over-long values and a cut-off tagline is the first
thing a reviewer sees.

Two things here are **not** drafted and cannot be: the compliance
acknowledgements, which are statements you personally make, and the test-account
credentials, which are written down at the bottom for you to fill in after you
create the account.

---

## Blocker before anything else

Anthropic's submission portal lives inside **organisation admin settings**, and
their docs say plainly that *"Admin settings aren't available on individual
plans."* You need a **Claude Team or Enterprise organisation** to reach
`claude.ai/admin-settings/directory/submissions/new`. Nothing else on this page
matters until that exists.

OpenAI has no equivalent plan gate, but does require **identity verification** on
the OpenAI developer platform before an app can be submitted.

---

## Listing copy

### Name
```
Osmos
```
5 characters. Fits Anthropic's 100 and OpenAI's 30.

### Tagline (Anthropic, max 55)
```
Shared project memory for your AI assistants
```

### Short description (OpenAI)
```
Give every AI assistant you use the same memory of your project.
```

### Description (Anthropic, max 2000)
```
Osmos gives your AI assistants a shared memory of your project.

Every assistant starts each conversation knowing nothing. You re-explain the
same decisions, the same constraints, the same reasons you ruled something out —
to Claude in the morning and to ChatGPT in the afternoon. Osmos is the place
that knowledge lives instead.

Connect Osmos once and your assistant reads the project's shared context at the
start of a task and writes durable decisions back at the end. Switch to a
different assistant, or hand the project to a colleague, and the understanding
travels with the work rather than staying in one chat history.

What it is good at:

- Carrying decisions and constraints between assistants, so a choice made in one
  conversation is known in the next.
- Keeping a team working from the same understanding. Share a context the way you
  would share a document, with view or edit access.
- Answering "what did the assistant actually know when it said that". Every sync
  is recorded and readable.

How it treats your data:

- Memory content is never sent to any third party. Retrieval is lexical search
  inside the database — no embedding model, no summarisation model, nothing
  leaves.
- Private notes stay private. They are filtered out in the database query itself,
  before anything is ranked or rendered, so another member's assistant cannot see
  them. Withheld items are counted, never named.
- Assistants can read and write memory but can never share a context or grant
  anyone access. Only people can do that.
- Nothing is deleted to enforce a plan limit.

Free covers one context, three people and three connected assistants. Pro is $8
per person per month.
```

### Categories (Anthropic, 1–5)
Pick from the portal's list; these fit the product in priority order:
1. Productivity
2. Developer tools
3. Knowledge management

### URL slug (permanent once published)
```
osmos
```

### Documentation URL
```
https://withosmos.com/docs
```

### Privacy policy URL
```
https://withosmos.com/privacy
```

### Terms URL (OpenAI)
```
https://withosmos.com/terms
```

### Support contact
```
hello@withosmos.com
```

### Company
```
Osmos — operated by Sam Ethan Mathew (individual, not a company)
https://withosmos.com
```

---

## Example prompts

Anthropic asks for at least three that exercise **different tools**. These do,
and each is phrased the way a real user would say it rather than naming a tool.

1. **"What have we already decided about this project?"**
   Exercises `sac_sync_context` — compiles the shared context for the task and
   returns the decisions, constraints and open conflicts.

2. **"Remember that we're using Postgres, not MySQL, because we need full-text
   search."**
   Exercises `sac_remember_shared` — writes a durable decision every other
   assistant and member will now start from.

3. **"What contexts do I have, and switch me to the mobile app one."**
   Exercises `sac_list_contexts` and `sac_use_context` — the switching flow.

4. **"What changed in this project since I last worked on it?"**
   Exercises `sac_recent_changes` — the catch-up path when returning to work.

5. **"Show me the full detail behind that decision, including who recorded it."**
   Exercises `sac_get_memory` — full detail and provenance for one memory.

---

## Technical answers

| Portal question | Answer |
|---|---|
| Server URL | `https://withosmos.com/mcp` |
| Transport | Streamable HTTP |
| Same URL for every user? | Yes — one URL, per-user OAuth |
| Authentication | OAuth 2.1 with dynamic client registration (RFC 7591) and PKCE |
| Does it read, write, or both? | Both |
| Is the underlying API your own? | Yes — first-party, no third-party API is proxied |
| Personal health data? | No |
| Sponsored content? | No |
| Opens external links (`ui/open-link`)? | No — no allowed-link-URI list needed |
| Prerequisite for users | A free Osmos account at withosmos.com. Claude custom connectors additionally require a Claude Pro or Max plan; ChatGPT requires Developer mode |

### Tool annotations

All twelve tools carry a `title` plus the applicable hints, which is a hard
review requirement on both sides. Seven are read-only; the five that write
declare `destructiveHint: false`, which is true of the product — superseding a
memory marks the old revision replaced and both remain readable, so nothing an
assistant can call destroys a recorded fact. Every tool declares
`openWorldHint: false` because none of them reach beyond the caller's own
contexts. Pinned by `tests/test_tool_annotations.py`.

---

## Data-handling summary

Written to answer the privacy section directly rather than pointing at the policy.

- **Collected:** account email and display name; the memory content users and
  their assistants choose to record; which assistants are connected; a record of
  each sync for the "what did the AI see" trail.
- **Not collected:** no device or advertising identifiers, no third-party
  cookies, no behavioural profile. IP addresses appear only in rate-limit
  counters, kept 24 hours, used solely to refuse the next attempt.
- **Third parties:** Render (hosting and database, Oregon, United States), Resend
  (transactional email), Stripe (payments), and Google or GitHub only if the user
  chooses to sign in with them. **No memory content is sent to any of them**, and
  none to any model provider.
- **Retention:** memory is kept until the user retracts it or deletes the
  context. Sync records are kept 90 days. The audit trail is kept indefinitely.
  Account deletion on request removes the account and everything it holds
  (`python -m app.auth.cli delete-user <email>`).

---

## Assets

Rendered from `website/site/assets/osmos-mark-dark.svg`:

| File | Size | Public URL | For |
|---|---|---|---|
| `icon-64.png` | 64×64, 1,481 B | `https://withosmos.com/assets/icon-64.png` | OpenAI (must be under 5 KB) |
| `icon-256.png` | 256×256, 3.6 KB | `https://withosmos.com/assets/icon-256.png` | general listing use |
| `icon-512.png` | 512×512, 8.4 KB | `https://withosmos.com/assets/icon-512.png` | Anthropic listing icon |

They are served from the site, so a portal that wants a URL rather than an
upload can take one directly.

**Screenshots are still needed** if you submit as an MCP App rather than a plain
connector: 3–5 PNGs, at least 1000px wide, cropped to the response only with the
prompt excluded, plus the prompt text supplied separately. A plain remote
connector — which is what Osmos is — does not require them.

---

## Reviewer test account

Anthropic asks for *"credentials for a fully populated account"* and step-by-step
access instructions. **This account exists and is seeded.**

```
URL:      https://withosmos.com
Email:    reviewer@withosmos.com
Password: osmos-reviewer-2026-demo
Context:  "Osmos platform" — 12 shared memories across decision, constraint,
          requirement and observation, each carrying the reasoning behind it
```

That password is written down here on purpose and is not a secret: the account
exists to be handed to reviewers at two companies, and it holds nothing but
seeded demo content. It is not reused anywhere and owns nothing real. Rotate it
after the reviews conclude and the account can simply be deleted with
`delete-user`.

Paste these steps into the portal's test-access field:

```
1. In Claude, open Customize > Connectors > Add custom connector and enter:
   https://withosmos.com/mcp
2. Claude will send you to Osmos to sign in. Use the credentials above, then
   approve the consent screen. It names the account being connected and what
   the assistant will be allowed to do.
3. Ask: "What have we already decided about this project?"
   The assistant returns the project's decisions with the reasoning attached —
   for example why Postgres was chosen over MySQL, and why no memory content is
   allowed to leave the database.
4. Ask: "Remember that we decided to launch on a Friday, because support is
   thinner at the weekend."
5. Ask the question from step 3 again. The new decision is now included, and
   would be for any other assistant connected to the same context.
```

The address is on our own domain and forwards to a monitored inbox, so a
reviewer who replies to anything reaches a person.

Seeded with real project knowledge rather than filler on purpose. A reviewer
deciding whether this does something useful is reading the *content* of what
comes back; an empty or nonsense context reads as a broken connector.

---

## Still yours to do

1. Create a Claude **Team** organisation — nothing else unblocks without it.
2. Complete OpenAI **identity verification**.
3. Create and seed the **reviewer account**, then fill in the block above.
4. Answer the **seven compliance acknowledgements** in Anthropic's portal. They
   are personal statements about your connector; nobody can make them for you.
5. Decide the **listing slug** is final — Anthropic makes it permanent once
   published.
