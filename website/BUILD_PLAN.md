# Osmos Website — Build Plan

How the public site in `website/site/` is built, and the rules it is held to.

**Status:** v1 built — homepage, `/get-started`, `/security`.
**Stack:** hand-authored static HTML + CSS + vanilla JS. No build step, no dependencies.

---

## 1. Who this site is for

The single framing decision behind every page:

> **Nobody is going to read the repo.**

The site is written for someone who wants to get Osmos, understand what it does *for them*, and use
it in their day-to-day work — not for someone auditing an architecture. Consequences:

- The homepage sells **what your workday looks like with Osmos**, not what the system is
- Getting it running is presented as **installing a product**, as short as it genuinely is
- Docs and GitHub are tertiary links, never the primary path
- Every technical claim still has to be true (see §7)

---

## 2. Authority order

When two sources disagree, the higher one wins. This is not negotiable.

1. `../AI_BRAND_CONTEXT.md` + `../BRAND_GUIDELINES.md` — how it looks and reads
2. `../tokens.json` + `../osmos.css` — the actual values; never invent colors or spacing
3. `../WEBSITE_PLAN.md` — information architecture, section order, copy, anti-patterns
4. `../../README.md`, `../../docs/SETUP.md`, and the code — **product truth**, the ceiling on claims
5. `../research/` — craft reference only; loses every conflict

The governing brand rule:

> **The interface is calm and neutral; color appears when knowledge moves.**

---

## 3. File layout

```
website/site/
├── index.html           homepage
├── get-started.html     the install + connect path
├── security.html        what V1 actually enforces
├── osmos.css            copy of ../osmos.css (see below)
├── styles.css           design system; layered on osmos.css
├── osmos-moment.js      the interactive handoff demo
├── theme.js             theme toggle + no-flash init
└── assets/              logos, favicon, OG image
```

`site/osmos.css` is a **copy** of `../osmos.css`, so the folder deploys standalone as a web root.
Re-sync it whenever brand tokens change:

```bash
cp website/osmos.css website/site/osmos.css
```

`styles.css` never redefines a brand token — it only layers on top.

### Cascade trap, documented because it will bite again

`osmos.css` defines its theme variables under `[data-theme="dark"]` / `[data-theme="light"]`
(specificity 0,1,0). A plain `:root` block in `styles.css` has *equal* specificity and loads later,
so it silently wins and the light theme stops working — the page stays dark while
`[data-theme="light"]` component rules still apply, producing inverted buttons.

`styles.css` therefore scopes its dark defaults as `:root:not([data-theme="light"])`. Do not
"simplify" that back to `:root`.

### Why no build step

`osmos.css` is already plain CSS custom properties, so a bundler buys nothing. It keeps a Node
toolchain out of a Python repo, produces the fastest possible page, and means anyone can open
`index.html` and see the site. Migrate to Astro if the site passes ~4 pages and shared partials start
being copy-pasted.

---

## 4. Design system

Built on `../osmos.css`; `styles.css` adds only what is missing.

| Layer | Values |
|---|---|
| Type | Fluid `clamp()`. Hero 44–52px mobile → 64–80px desktop, weight 600, line-height 0.98–1.06. H2 32–44. Body 16. Body-large 18–20. |
| Layout | 1200–1280px container, 620–760px text measure, 8px spacing rhythm |
| Radius | 8px controls · 10–12px inputs · 16–20px marketing cards · 999px pills |
| Motion | micro 140–220ms · standard 220–360ms · handoff 600–1200ms · `cubic-bezier(0.22,1,0.36,1)` · no bounce |
| Themes | Dark default, full light theme, `prefers-color-scheme` respected, manual toggle persisted |

### Glass: exactly one surface

The sticky nav is the only glass element on the site, with an opaque fallback under
`prefers-reduced-transparency` and in browsers without `backdrop-filter`.

This is where the Apple research and the brand system agree exactly. Apple's 2025 HIG says
*"Don't use Liquid Glass in the content layer"* and *"use Liquid Glass effects sparingly"*;
`BRAND_GUIDELINES.md` says *"no glassmorphism overload."* A marketing site is almost entirely content
layer — so the nav, which genuinely floats above scrolling content, is the one correct use.

Full reasoning: `../research/02-liquid-glass.md`.

---

## 5. Contrast constraints

Computed from the brand palette using WCAG 2.1 relative luminance. **The flow palette is
dark-theme-native** — this is a measured constraint, not a preference:

| Color | On Ink 950 (dark) | On #F7FAFF (light) |
|---|---|---|
| Mineral White `#F7FAFF` | 18.08:1 ✅ AAA | — |
| Mist `#A9B3C5` | 8.95:1 ✅ AAA | — |
| Aqua 400 `#30C4F4` | 9.30:1 ✅ AAA | **1.94:1 ❌ fails everything** |
| Blue 400 `#3E8CFF` | 5.76:1 ✅ AA | 3.14:1 ⚠️ large text / UI only |
| Indigo 400 `#6666FF` | 4.42:1 ⚠️ large / UI only | — |
| Violet 500 `#B02EFF` | 4.22:1 ⚠️ large / UI only | 4.29:1 ⚠️ large / UI only |
| Violet 400 `#8A4DFF` | 4.13:1 ⚠️ large / UI only | — |

Rules this forces:

1. **No flow color is ever used for body text**, in either theme. This confirms the warning already
   in `BRAND_GUIDELINES.md`.
2. **Light theme uses a darkened flow ramp.** The brand gradient is unusable on `#F7FAFF` — Aqua 400
   measures 1.94:1, below even the 3:1 graphical-object threshold. Light theme therefore substitutes
   `#8E22CC → #6E3ACC → #4F4FD1 → #2C6ACC → #1B87A8`, same hue progression, measured **3.95–6.39:1**.
   This applies to the hero gradient text *and* the Osmos Moment strokes.
3. Body text is Mineral White / Mist on dark and Ink 950 / `#5F6B7B` on light — all comfortably AA+.
4. Color never solely carries meaning. Every state also has text or shape.

**Watch out:** gradient text sets `color: transparent`, so automated contrast checkers skip it
entirely. The hero headline has to be verified by checking each gradient stop by hand. That is how
the light-theme aqua failure was found — after an automated pass reported zero problems.

---

## 6. The interactive Osmos Moment

The most important element on the site.

**Design idea:** the logo's white horizontal axis *is* the shared project layer. The demo is the
logo, animated at page scale. This needs no new metaphor — it is already the brand's own semantics
per `AI_BRAND_CONTEXT.md` ("white axis = persistent shared project layer").

Sequence, 600–1200ms, `cubic-bezier(0.22,1,0.36,1)`, no bounce:

1. Left card holds a captured decision with a source badge
2. A violet pulse leaves the card and enters the white axis
3. The project revision ticks `r41 → r42` — a calm increment
4. The pulse traverses violet → indigo → blue → aqua along the axis
5. The right card illuminates; its response contains the transferred decision
6. A provenance chip resolves: source user, source agent, revision, elapsed time

Controls: **Replay** · **Without Osmos / With Osmos** · **View provenance**. Nothing requires typing
before the visitor understands it.

Implementation is inline SVG plus CSS custom-property transitions driven by a small state machine in
`osmos-moment.js`. No animation library.

- `prefers-reduced-motion` → renders the completed end state immediately; controls still work. Not a
  degraded experience — a static diagram making the same point.
- Mobile stacks vertically and the pulse travels top-to-bottom.
- Uses the real MCP tool names from `app/api/mcp_tools.py`: `sac_sync_context`, `sac_remember_shared`.

Why interactive rather than video: direct manipulation is the oldest and most-cited principle in
Apple's HIG, and it is the strongest available proof for a product with nothing to photograph.

---

## 7. Honesty constraints

Enforced from `WEBSITE_PLAN.md` §21 and the product's own principle #4, *"Humans Must Be Able to
Inspect the Brain."* A site that overstates the product contradicts the product's thesis.

- **Provider states.** *Available:* Claude, ChatGPT, MCP, REST API — documented and working in
  `docs/SETUP.md`. *Planned:* Codex, Claude Code, Cursor, Gemini. Never labelled Available.
- **Dev mode caveat** stated wherever the local track appears: `SAC_AUTH_MODE` defaults to `dev`
  (`app/api/deps.py:20`), which identifies callers by an actor email, is spoofable by design, and
  must never be used on a public deployment (`app/api/deps.py:3-6`).
- **Sensitivity gap** stated on `/security`: labels are stored and `secret` is refused at write time,
  but per-grant sensitivity ceilings are not yet enforced (`docs/SETUP.md:150`).
- **No** invented metrics, customer logos, testimonials, or prices. **No** compliance claims —
  no SOC 2, ISO, HIPAA.
- V1 limits stated where relevant: deterministic lexical ranking, no embeddings yet.

### Deliberate omissions

- **Social proof section** — no genuine metrics, quotes, or logos exist. `WEBSITE_PLAN.md` §15
  forbids fabricating them, and a "coming soon" block is worse than nothing. Left as an HTML comment
  recording what evidence would unlock it.
- **Video sections** — reserved as poster slots at the correct position and aspect ratio. The 45–75s
  film in `WEBSITE_PLAN.md` §7 has to be produced separately.

---

## 8. Analytics

Event hooks ship as `data-osmos-event` attributes only. **No third-party analytics script.** A
product positioned on privacy and inspectability that ships surveillance analytics would contradict
itself. Event names match `WEBSITE_PLAN.md` §18 so any provider — or a self-hosted endpoint — can be
wired later by reading the attributes.

---

## 9. Apple principles, applied

| Principle | How it shows up |
|---|---|
| Deference to content | Neutral surfaces throughout; color only where knowledge moves |
| Direct manipulation | The Osmos Moment is interactive, not a video |
| One idea per section | Each section makes one claim; two claims means it splits |
| Motion explains | Only the handoff animates. No scroll-reveal on everything |
| Feedback | The demo has visible state; copy buttons confirm |
| Forgiveness | Replay always available; no dead ends |
| Perceived stability | Persistent nav, one grid, consistent section rhythm |
| User control | No scroll hijacking, no autoplay audio, no email gate |
| Knowledge of audience | Written for a working developer, not a repo auditor |

Sources and the full principle set: `../research/01-apple-design-principles.md`.

---

## 10. Accessibility targets

Held to the thresholds in `../research/03-web-platform-rules.md`:

- Text contrast 4.5:1 normal, 3:1 large (≥24px or ≥18.66px bold) and UI components
- Focus indicators visible at 3:1 against adjacent colors
- Touch targets 44×44 CSS px minimum, 24px spacing between adjacent targets
- Body line-height ≥1.5, measure ≤75ch
- Semantic HTML, one `<main>`, correct heading outline, skip link
- `prefers-reduced-motion`, `prefers-contrast`, `prefers-reduced-transparency`, `prefers-color-scheme`
- Explicit `width`/`height` on images to prevent layout shift
- Never `user-scalable=no`

---

## 11. Deploying

The site is standalone static files — no server required, and **no changes to the FastAPI app**.

Note that `app/main.py:200` mounts the MCP app at `/`, so the API service's domain root is already
taken. The site therefore wants either its own host (`www.<domain>` with the service on
`api.<domain>`) or any static host: Render static site, Netlify, Cloudflare Pages, GitHub Pages.

Locally:

```bash
python -m http.server -d website/site 8080
```

---

## 12. Not built yet

- The two product videos — placeholders only
- Real social proof — needs genuine data
- `/product`, `/how-it-works`, `/developers`, `/pricing`, integration pages — P1 in `WEBSITE_PLAN.md`
- Domain, DNS, and deploy — needs a hosting decision
- Self-hosted Inter woff2 files — the site currently uses the documented fallback stack
