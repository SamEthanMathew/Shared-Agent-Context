# Osmos Website Plan

> Implementation blueprint for the public website, setup funnel, product demo, and launch experience.

**Status:** launch-planning document  
**Brand source of truth:** `website/BRAND_GUIDELINES.md`, `website/AI_BRAND_CONTEXT.md`, `website/tokens.json`, `website/osmos.css`, `website/assets/`

> Naming note: **Osmos is still a working brand name and has known naming/collision risk. Do not treat this document as trademark clearance.** The website architecture should make the brand name easy to replace without restructuring the product story.

---

## 1. Website objective

The website has one primary job:

> **Make a visitor understand the cross-agent handoff in under 30 seconds and get a team into setup with minimal friction.**

Secondary jobs:

- establish technical credibility;
- show that Osmos is not another chat app or generic AI-memory product;
- demonstrate privacy, provenance, and control;
- give developers a direct path to docs and GitHub;
- provide a credible enterprise/security path without forcing self-serve users through sales;
- create a launch asset that is easy to share on X, LinkedIn, Hacker News, Product Hunt, GitHub, and MCP ecosystems.

The site should feel like a premium infrastructure/devtool company, not a generic AI SaaS landing page.

---

## 2. Primary audiences

### A. AI-native startup teams
Two to twenty people using combinations of ChatGPT, Claude, Codex, Claude Code, Cursor, Gemini, etc.

Their question:
> "Can my teammate's agent automatically know what my agent learned?"

### B. Developers / technical founders
They care about MCP, APIs, architecture, integrations, provenance, reliability, and setup speed.

Their question:
> "Can I connect this to my current workflow without adopting another workspace?"

### C. Research teams / labs
They care about persistent decisions, findings, experiments, evidence, and cross-researcher context.

### D. Enterprise / platform buyers later
They care about permissions, auditability, identity, retention, governance, security, and provider independence.

The homepage should primarily serve A + B. Enterprise depth lives on separate pages.

---

## 3. Core website story

Do not lead with "AI memory."

Lead with the visible outcome:

> **One agent learns something. Another agent already knows.**

The canonical story is the **Osmos Moment**:

```text
Person A / Agent A
        |
        | learns a durable decision
        v
      Osmos
        |
        | shared project knowledge + provenance
        v
Person B / Agent B
        |
        | uses it automatically
        v
better action / response
```

Everything on the site should reinforce this flow.

---

## 4. Recommended top navigation

Desktop:

```text
[Osmos logo]   Product   How it works   Developers   Security   Pricing   [GitHub]   Log in   [Set up Osmos]
```

Recommended behavior:

- **Product** -> `/product`
- **How it works** -> `/how-it-works`
- **Developers** -> `/developers` or docs subdomain when available
- **Security** -> `/security`
- **Pricing** -> `/pricing`
- **GitHub** -> public repository when ready
- **Log in** -> hosted app/dashboard
- **Set up Osmos** -> `/setup`

On launch, the primary button should say **Set up Osmos** rather than "Book a demo".

The product should be self-serve wherever technically possible.

Mobile nav should collapse to:

```text
Product
How it works
Developers
Security
Pricing
GitHub
Log in
[Set up Osmos]
```

Keep the setup button visible as the dominant action.

---

## 5. Recommended sitemap

### Launch-critical

```text
/
/setup
/how-it-works
/product
/developers
/security
/pricing
/login -> app
/docs -> docs surface
```

### Useful shortly after launch

```text
/use-cases/startups
/use-cases/engineering
/use-cases/research
/integrations
/integrations/chatgpt
/integrations/claude
/integrations/codex
/integrations/claude-code
/integrations/cursor
/changelog
/blog
/about
```

### Later enterprise

```text
/enterprise
/security
/trust
/docs/admin
/docs/permissions
/docs/audit
```

---

# 6. Homepage section order

The homepage should be intentionally linear. Do not dump every feature above the fold.

## Section 1: Hero

Dark, spacious, centered.

### Recommended headline

> **Different people. Different agents. Same project understanding.**

### Supporting line

> Osmos keeps your team's AI agents working from the same continuously updated project knowledge across models, accounts, sessions, and tools.

### CTAs

Primary:

> **Set up Osmos**

Secondary:

> **Watch the handoff**

Tertiary text link:

> View GitHub / Read the docs

### Hero visual

Do not use a static abstract blob.

Use an **interactive Osmos Moment**:

```text
LEFT                            SHARED LAYER                           RIGHT

Sam / ChatGPT                     OSMOS                           Matthew / Claude

"Use opaque cursor        -> decision captured ->       "Since this project uses
pagination."                                            opaque cursor pagination..."
```

The visitor should visually see one decision travel from one agent environment to the other.

The brand color appears only while the information moves.

---

## Section 2: Provider / workflow strip

A quiet row of supported/target systems in monochrome:

```text
ChatGPT   Claude   Codex   Claude Code   Cursor   Gemini   MCP   API
```

Do not overstate support. Only label something "Available" when it works.

Use three states if needed:

- Available
- Preview
- Planned

---

## Section 3: The problem

Headline:

> **Your team collaborates. Your agents don't.**

Visualize three common failures:

1. repeated research;
2. stale architecture decisions;
3. manual copy/paste between chats and agents.

Use a split visual:

```text
WITHOUT OSMOS
ChatGPT -> isolated
Claude  -> isolated
Codex   -> isolated

WITH OSMOS
ChatGPT --\
Claude  ----> shared project understanding
Codex   --/
```

Keep copy short and problem-oriented.

---

## Section 4: Osmos Moment product demo

This should be the most important section after the hero.

Headline:

> **Tell one agent once. The project remembers.**

Demo sequence:

1. ChatGPT or Claude captures a durable project decision.
2. Osmos shows the project revision increment.
3. Provenance appears: source user, source agent, timestamp, type.
4. A second user opens a different provider/client.
5. The second agent uses the information without manual copy/paste.
6. UI marks the successful event as a **Context Handoff** / **Osmos Moment**.

This section should support both an interactive animation and a full video modal.

CTA:

> **Try this with your team**

links to `/setup`.

---

## Section 5: Three core product pillars

Use three large premium cards, not a 12-feature grid.

### Shared project context

> Decisions, findings, constraints, results, and project knowledge can follow the project instead of being trapped inside one agent.

### Private when it should be

> Keep private project context private. Share only what belongs in the team context.

### Know where it came from

> Every durable item carries provenance, revision history, and source information.

Optional fourth pillar:

### Model independent

> Switch tools and models without resetting your team's understanding.

---

## Section 6: How it works

Simple three-step flow:

### 1. Connect
Connect supported agents or clients to an Osmos project.

### 2. Work normally
Keep using ChatGPT, Claude, Codex, Cursor, or your existing tools.

### 3. Knowledge moves
Osmos captures durable project context and returns the right context to the right agent.

Show the product architecture at a high level, but keep it understandable.

---

## Section 7: Video 1 - primary product film

### Title
**The Osmos Moment**

### Length
45-75 seconds.

### Placement
Homepage directly after "How it works" or inside the primary product-demo section.

### Playback
- poster frame visible by default;
- autoplay only for a silent 6-10 second looping preview;
- full video plays on click;
- captions always available;
- do not autoplay sound;
- respect reduced-motion preferences.

### Storyboard

**0-5 sec**  
Two people, two different AI tools. Text: "Your team uses different agents."

**5-15 sec**  
Agent A learns: "All public APIs use opaque cursor pagination."

**15-25 sec**  
A violet pulse leaves Agent A, enters the white Osmos axis, revision increments, provenance appears.

**25-40 sec**  
Person B opens Claude in a different account/session and asks it to implement an endpoint.

**40-55 sec**  
Claude responds using the cursor-pagination decision automatically.

**55-65 sec**  
UI reveals: "Context handoff: ChatGPT -> Claude" with source and timestamp.

**65-75 sec**  
Logo + line:

> Different people. Different agents. Same project understanding.

CTA:

> Set up Osmos

This video should feel like a real product proof, not a cinematic AI montage.

---

## Section 8: Developer credibility

Headline:

> **Built to sit between your tools, not replace them.**

Show:

- MCP
- REST/API
- SDKs when available
- GitHub
- example code snippet
- provider-neutral architecture

Example code card:

```text
sac_sync(task="implement message pagination")

-> decision: public APIs use opaque cursor pagination
-> source: Sam / ChatGPT
-> revision: r42
```

Actions:

- Read docs
- View GitHub
- Setup with MCP

Do not hide technical implementation behind marketing copy.

---

## Section 9: Trust, privacy, provenance

Headline:

> **Shared deliberately. Traceable by default.**

Three or four concise areas:

### Visibility
Private / project / organization scopes.

### Permissions
Separate read/write access for clients and users.

### Provenance
Who, what agent, what source, and when.

### Revision history
See what changed and what superseded previous knowledge.

CTA:

> Read security & privacy architecture

Do not imply compliance certifications until actually obtained.

---

## Section 10: Social proof

### Before meaningful customer traction
Use only authentic evidence:

- founding team count;
- context handoffs completed;
- integrations connected;
- GitHub stars if meaningful;
- short quotes from real alpha teams;
- research/startup team logos only with permission.

Never fabricate usage counts or customer logos.

### After traction
Prioritize quotes that describe the magic moment:

> "Claude picked up an architecture decision my cofounder made in ChatGPT the night before."

This is much stronger than generic praise.

---

## Section 11: Video 2 - optional deeper technical demo

### Title
**How Osmos works in 2 minutes**

### Length
90-150 seconds.

### Placement
Homepage lower section + `/how-it-works` + docs getting-started page.

### Story
1. Create project.
2. Invite collaborator.
3. Connect two different clients.
4. Publish/capture a decision.
5. Sync second client.
6. Show retrieved context.
7. Show provenance and revision.
8. Show private vs shared visibility.

This video should be a crisp product walkthrough recorded from the real product.

---

## Section 12: Pricing preview

Early stage recommendation:

Keep pricing simple and self-serve.

Potential structure:

```text
Developer / Free
- 1 shared project
- limited members/context usage
- core integrations

Team
- multiple projects
- larger context usage
- permissions
- history
- team controls

Enterprise
- SSO
- advanced audit
- retention / governance
- private deployment options
- support
```

Do not invent final prices until product economics and willingness-to-pay are tested.

Homepage copy can say:

> Start free. Upgrade when your team needs more projects, usage, or controls.

---

## Section 13: FAQ

Keep to 5-7 questions.

Recommended:

1. Is Osmos another chat app?
2. Does Osmos read my entire ChatGPT/Claude history?
3. What gets shared with teammates?
4. Which AI tools does Osmos support?
5. Can I keep some project context private?
6. How does provenance work?
7. Can I self-host / use an API?

---

## Section 14: Final CTA

Dark neutral section with one controlled gradient flow entering the logo.

Headline:

> **Your agents shouldn't have to start over.**

Supporting line:

> Give your team one evolving project understanding across the AI tools they already use.

Primary CTA:

> **Set up Osmos**

Secondary:

> Read the docs

---

# 7. Hero headline alternatives

Recommended primary:

> **Different people. Different agents. Same project understanding.**

Alternatives to test:

1. **Your teammate's AI should know what your AI knows.**
2. **One project understanding across every agent.**
3. **What one agent learns, the rest can use.**
4. **Stop copying context between AI agents.**
5. **Keep every agent on the same project page.**
6. **Project knowledge that moves with your team.**
7. **Your project should remember across every AI tool.**
8. **Shared context for teams working across AI agents.**
9. **One agent learns. The project knows.**
10. **The shared context layer for AI-native teams.**

A/B testing should compare an emotional/obvious line (#1) against the category-defining line (recommended primary).

---

# 8. CTA hierarchy

## Primary site CTA

**Set up Osmos**

Destination:

`/setup`

Do not send the main CTA to a generic signup page with no context.

## Secondary CTA

**Watch the handoff**

Scrolls to or opens the Osmos Moment video/demo.

## Developer CTA

**Read the docs**

## Trust CTA

**Security & privacy**

## Enterprise CTA

**Contact sales**

Enterprise should be available but should not dominate the homepage.

---

# 9. Setup / installation funnel

The `/setup` page is part of the product experience and should feel as polished as the homepage.

## `/setup` step 0 - Choose your path

Headline:

> **Set up your shared project context.**

Choices:

- Connect with MCP
- Connect ChatGPT
- Connect Claude / Claude Code
- Connect Codex / coding agent
- API / SDK

Only show install paths that actually exist.

## Step 1 - Sign in

Preferred friction:

- email / Google / GitHub where appropriate;
- avoid long onboarding forms.

## Step 2 - Create project

Fields:

- project name
- optional short description

Then immediately create the project.

## Step 3 - Connect first agent

Show a guided setup panel with copyable config or OAuth/app connection depending on integration.

Success state:

> **Agent connected.**

## Step 4 - Invite teammate / connect second agent

This is critical because Osmos is inherently multiplayer.

CTA:

> **Invite the person whose AI should know what yours knows.**

Alternative:

> Connect another agent

## Step 5 - Trigger first handoff

Give the user an explicit test:

> In Agent A, save or publish this decision: "Public APIs use opaque cursor pagination."

Then:

> Open Agent B and ask: "How should pagination work in this project?"

When it succeeds, show:

```text
Osmos Moment
Context handoff complete
Agent A -> Agent B
Source + revision + timestamp
```

This should be celebratory but restrained.

## Step 6 - Dashboard

Button:

> Open project

The user lands in a project control plane showing:

- connected agents
- recent context changes
- revisions
- provenance
- private/shared visibility
- recent handoffs

---

# 10. Suggested route / URL structure

Use domain-neutral paths for now:

```text
/                      marketing homepage
/setup                 guided setup
/login                 login
/app or app subdomain  control plane
/docs                   documentation
/docs/getting-started
/docs/mcp
/docs/api
/docs/integrations
/product
/how-it-works
/security
/pricing
/developers
/integrations
/changelog
```

If using subdomains later:

```text
www.<domain>      marketing
app.<domain>      product/dashboard
docs.<domain>     docs
status.<domain>   uptime/status
```

Do not hardcode a final public domain until naming/domain work is complete.

---

# 11. Design specification

Follow `website/BRAND_GUIDELINES.md`.

## Container

- desktop max-width: ~1200-1280px;
- text measure: 620-760px for major copy;
- hero can use wider visual stage;
- use an 8px spacing system.

## Background

Primary:

`#0B111B`

Raised surfaces:

`#111827`, `#162033`

Primary text:

`#F7FAFF`

Secondary:

`#A9B3C5`

## Flow colors

```text
#B02EFF
#8A4DFF
#6666FF
#3E8CFF
#30C4F4
```

## Gradient rule

> **Color appears when knowledge moves.**

Do not use the gradient as a page background.

Use it for:

- moving pulses;
- handoff paths;
- active provenance trails;
- selected flow states;
- small highlights;
- branded video transitions.

## Typography

Inter.

Hero desktop: 64-80px / 600  
Hero mobile: 44-52px / 600  
H2: 36-48px / 600  
Body large: 18-20px  
Body: 16px

## Cards

- 16-20px radius marketing cards;
- subtle border rather than heavy shadow;
- dark-on-dark depth;
- no glassmorphism overload;
- no glowing neon outlines by default.

## Buttons

Primary:

- Mineral White or restrained Blue fill;
- high contrast;
- 10-12px radius;
- 44px+ touch height.

Gradient buttons should not be the default.

## Provider logos

Prefer monochrome / low-contrast provider marks so Osmos remains visually dominant.

## Motion

- micro: 140-220ms
- normal: 220-360ms
- handoff: 600-1200ms
- ease-out / `cubic-bezier(0.22,1,0.36,1)`
- no bouncing
- honor `prefers-reduced-motion`

---

# 12. Interactive Osmos Moment specification

The homepage should include a lightweight interactive demonstration, not only video.

## Default animation

1. Left agent card contains a new decision.
2. Decision receives a source badge.
3. A violet pulse travels to the center.
4. Shared project revision changes from `r41` to `r42`.
5. Pulse transitions through violet -> indigo -> blue -> aqua.
6. Right agent card activates.
7. Right agent response contains the transferred project decision.
8. Provenance chip appears:

```text
Used from Osmos
Sam / ChatGPT
Decision r42
18 sec ago
```

## User interaction

Visitors can click:

- Replay
- View provenance
- Show without Osmos / with Osmos

Do not make the demo require typing before the visitor understands it.

---

# 13. Developer page

`/developers`

Should contain:

- concise architecture explanation;
- MCP quickstart;
- API quickstart;
- SDK links when available;
- examples;
- GitHub CTA;
- local/self-host story if supported;
- authentication/scopes explanation;
- provenance/revision data model;
- link to full docs.

Hero:

> **Give any agent the project context it needs.**

The developer page can be more technical than the homepage.

---

# 14. Security page

`/security`

Must be factual and scoped to what exists today.

Sections:

- project isolation;
- client identity;
- read/write scopes;
- private/shared context;
- sensitivity labels;
- authorization before inference;
- provenance;
- revocation;
- audit/history;
- data retention when implemented;
- infrastructure/compliance when implemented.

Never show SOC 2, ISO, HIPAA, etc. unless actually obtained/applicable.

---

# 15. Social proof strategy

## Pre-launch / alpha

Good proof:

- "12 founding teams"
- "1,483 context handoffs"
- "5 connected agent clients"
- real quote with permission

Bad proof:

- made-up logos
- invented stats
- vague "trusted by leading AI teams"

## Later

Prioritize case studies where Osmos prevented duplicated work, stale assumptions, or context loss.

---

# 16. SEO / category positioning

Do not rely only on the brand name.

Core concepts to build pages around:

- shared context for AI agents
- team context for AI
- cross-agent context
- AI agent collaboration
- context handoff
- shared project memory for AI agents
- MCP shared context
- Claude ChatGPT shared context
- agent coordination infrastructure

Suggested homepage title:

> Osmos - Shared project context for AI agents

Suggested meta description:

> Keep your team's AI agents working from the same evolving project knowledge across models, accounts, sessions, and tools, with provenance and permissions built in.

Integration pages can target specific high-intent searches without making the brand provider-dependent.

---

# 17. Launch-day website changes

Launch version can add a temporary announcement strip:

> **Osmos is now in developer preview ->**

or

> **Now open for founding teams ->**

Homepage should make the launch video highly visible.

Launch-day header may temporarily prioritize:

```text
Product | Docs | GitHub | Security | [Set up Osmos]
```

Keep it simpler than the evergreen navigation.

---

# 18. Analytics events

Track the actual funnel, not vanity page views alone.

Core events:

```text
homepage_view
hero_setup_click
hero_video_play
hero_demo_replay
docs_click
github_click
setup_started
signup_completed
project_created
first_agent_connected
invite_sent
second_agent_connected
first_context_published
first_context_retrieved
first_context_handoff
osmos_moment_completed
project_returned_day_1
project_returned_day_7
pricing_view
enterprise_contact
```

### North-star website conversion

Visitor -> setup started -> two agents/users connected -> first successful context handoff.

The meaningful conversion is not account creation. It is reaching the first Osmos Moment.

---

# 19. A/B tests worth running

Do not test tiny color changes before messaging.

High-value tests:

1. Hero headline:
   - "Different people. Different agents. Same project understanding."
   - "Your teammate's AI should know what your AI knows."

2. Primary CTA:
   - Set up Osmos
   - Start free

3. Hero media:
   - interactive handoff
   - 8-second loop + play button

4. Social proof position:
   - immediately below hero
   - after Osmos Moment demo

5. Setup ask:
   - create project first
   - connect agent first

---

# 20. Mobile requirements

On mobile:

- hero headline should fit comfortably in 3-5 lines;
- stack Agent A / shared layer / Agent B vertically;
- animate the handoff top-to-bottom rather than left-to-right;
- provider logos become horizontally scrollable or wrap cleanly;
- primary CTA stays full-width or near-full-width;
- video should use a 16:9 or optimized vertical crop without tiny UI text;
- avoid horizontally compressed architecture diagrams;
- no critical interaction should depend on hover.

---

# 21. Anti-patterns

Do not ship:

- generic rainbow AI gradient background;
- huge animated blob behind every section;
- fake neural network art;
- robot / brain stock images;
- "revolutionary AI memory" language;
- a homepage that feels like another chat app;
- 10+ equal-weight feature cards;
- a sales-call gate for basic product setup;
- autoplay audio;
- excessive scroll-jacking;
- unsubstantiated customer logos or metrics;
- security/compliance claims that are not implemented;
- provider logos larger/more colorful than the Osmos brand;
- complicated onboarding before the first agent is connected.

---

# 22. Research-backed patterns used

The research informing this plan found recurring patterns across successful developer/SaaS landing pages:

- centered, clear hero with one primary value proposition and supporting product visual;
- immediate or early trust signals;
- problem-oriented storytelling rather than feature inventories;
- concise product demos and video used to make technical behavior obvious;
- restrained visual systems and generous whitespace;
- developer products benefit from interfaces that feel native to technical users;
- curated testimonials are more credible than random social posts;
- setup/sign-up friction should be minimized;
- clear CTAs should repeat at the point of decision rather than only once at the top.

Research references included the Evil Martians analysis of 100 developer-tool landing pages, Unbounce landing-page video research, and current SaaS landing-page pattern studies. These patterns should inform Osmos, not be copied mechanically.

---

# 23. Implementation roadmap

## P0 - launch critical

- responsive homepage;
- final hero copy;
- `Set up Osmos` -> `/setup`;
- interactive Osmos Moment;
- primary 45-75 second product video;
- supported integrations strip;
- three product pillars;
- how-it-works section;
- developer credibility section;
- privacy/security section;
- basic social proof when genuine;
- FAQ;
- final CTA;
- setup funnel;
- docs link;
- GitHub link;
- analytics events;
- mobile implementation;
- SEO metadata;
- OG/social share image.

## P1 - shortly after launch

- deeper `/product` page;
- `/how-it-works`;
- `/developers`;
- `/security`;
- `/pricing`;
- integration pages;
- second 2-minute technical walkthrough video;
- case studies;
- changelog;
- refined docs.

## P2 - later

- enterprise page;
- trust center;
- customer stories;
- benchmark/evaluation pages;
- organization features;
- SSO/admin documentation;
- partner/ecosystem pages;
- interactive product sandbox.

---

# 24. Homepage wireframe

```text
+---------------------------------------------------------------+
| OSMOS     Product  How it works  Developers  Security Pricing |
|                                             Log in [Set up]    |
+---------------------------------------------------------------+

                    Different people.
                    Different agents.
                 Same project understanding.

          Osmos keeps your team's agents working from
          the same evolving project knowledge.

             [ Set up Osmos ]  [ Watch the handoff ]
                         View GitHub

                 [INTERACTIVE OSMOS MOMENT]

        ChatGPT  Claude  Codex  Claude Code  Cursor  MCP

+---------------------------------------------------------------+
| Your team collaborates. Your agents don't.                   |
| isolated context -> repeated work -> stale decisions          |
+---------------------------------------------------------------+

+---------------------------------------------------------------+
| THE OSMOS MOMENT                                              |
| Agent A -> shared decision -> provenance -> Agent B           |
| [Replay] [View provenance] [Try with your team]               |
+---------------------------------------------------------------+

+-------------------+-------------------+------------------------+
| Shared context    | Private/shared    | Provenance             |
| project knowledge | visibility        | source + revision      |
+-------------------+-------------------+------------------------+

+---------------------------------------------------------------+
| How it works                                                   |
| 1 Connect -> 2 Work normally -> 3 Knowledge moves             |
+---------------------------------------------------------------+

+---------------------------------------------------------------+
| VIDEO: The Osmos Moment                                        |
| real ChatGPT -> Osmos -> Claude workflow                       |
+---------------------------------------------------------------+

+---------------------------------------------------------------+
| Built to sit between your tools, not replace them              |
| MCP | API | GitHub | code sample                               |
+---------------------------------------------------------------+

+---------------------------------------------------------------+
| Shared deliberately. Traceable by default.                     |
| privacy | permissions | provenance | revisions                 |
+---------------------------------------------------------------+

+---------------------------------------------------------------+
| Genuine founding-team proof / quote / handoff metrics          |
+---------------------------------------------------------------+

+---------------------------------------------------------------+
| FAQ                                                            |
+---------------------------------------------------------------+

+---------------------------------------------------------------+
| Your agents shouldn't have to start over.                      |
| [ Set up Osmos ]   Read the docs                               |
+---------------------------------------------------------------+

Footer:
Product | Developers | Docs | Security | Pricing | GitHub | Blog
Company | About | Contact | Privacy | Terms
```

---

# 25. Instruction to AI coding agents

When implementing the website:

1. Read `website/AI_BRAND_CONTEXT.md`.
2. Read `website/BRAND_GUIDELINES.md`.
3. Use `website/tokens.json` and `website/osmos.css` rather than inventing colors/spacing.
4. Use logo assets from `website/assets/`.
5. Treat this file as the information architecture and content blueprint.
6. Keep the homepage story centered on a real cross-agent context handoff.
7. Do not replace the product proof with generic AI imagery.
8. Preserve accessibility and reduced-motion behavior.
9. Do not claim an integration, security feature, customer, or metric unless it is actually available/verified.
10. The primary conversion path is `/setup` and should remain easy to find throughout the site.

The most important implementation test is simple:

> A new technical visitor should understand what Osmos does, watch or interact with a cross-agent handoff, and know exactly how to set it up without needing a sales call.
