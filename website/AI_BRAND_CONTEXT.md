# Osmos Website Brand Context for AI Coding Agents

Read this file before creating or modifying any Osmos website, landing page, dashboard, docs site, marketing page, social card, launch visual, or other user-facing website surface.

## What Osmos is
Osmos is shared-context and coordination infrastructure for teams using multiple AI agents and models. Its core user-visible magic moment is a cross-agent context handoff: one person’s agent learns something durable and another person’s independent agent can use it automatically.

## Brand rule in one sentence
**The interface is calm and neutral; color appears when knowledge moves.**

## Required visual system
### Backgrounds
- Dark primary: `#0B111B`
- Dark surface: `#111827`
- Dark elevated: `#162033`
- Light primary: `#F7FAFF`
- Light surface: `#FFFFFF`

### Text
- Dark-mode primary: `#F7FAFF`
- Dark-mode secondary: `#A9B3C5`
- Light-mode primary: `#0B111B`
- Light-mode secondary: `#5F6B7B`

### Osmos flow colors
In left-to-right order:
1. `#B02EFF`
2. `#8A4DFF`
3. `#6666FF`
4. `#3E8CFF`
5. `#30C4F4`

Gradient:
`linear-gradient(90deg,#B02EFF 0%,#8A4DFF 25%,#6666FF 50%,#3E8CFF 75%,#30C4F4 100%)`

### Typography
Primary family: **Inter**.
Fallback: `Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`.
Use 400 body, 500 labels/nav, 600 headings. Avoid 800/900 unless a specific campaign requires it.

### Geometry
- 8px spacing system
- normal control radius 8–12px
- marketing card radius 16–20px
- do not over-round everything
- generous whitespace on marketing surfaces

## Logo semantics
The Osmos mark uses a white horizontal axis behind five violet-to-cyan vertical/curved streams.
- white axis = persistent shared project layer
- colored streams = independent humans/agents/models/sources
- convergence = shared understanding

Do not reinterpret the logo as a flower, soundwave, radio signal, brain, or biological membrane in copy.

## Do
- prefer dark, minimal hero areas
- use restrained flow-gradient accents
- show real cross-agent handoffs
- show provenance, revision, source, and destination clearly
- use clean diagrams and strong hierarchy
- keep supported-provider logos monochrome where possible
- make privacy/permissions feel first-class and legible

## Do not
- use rainbow backgrounds
- use neon cyberpunk grids
- use random gradient blobs
- use brains, robot heads, neural-network webs, or circuit-board stock art
- use literal water droplets as the main brand metaphor
- make every button a gradient
- imitate Anthropic cream/orange branding
- make the product look like another chat interface

## Website hero default
Headline: **Different people. Different agents. Same project understanding.**
Supporting copy: Osmos keeps humans and AI agents working from the same continuously updated project knowledge across models, accounts, sessions, and tools.
Primary CTA: `Start building` or `Start free` depending on product state.
Secondary CTA: `Watch the handoff` / `See how it works`.

## Product animation default
When visualizing a context handoff:
1. source agent/person emits a small flow-colored pulse;
2. pulse enters the shared horizontal axis;
3. the center/shared context activates;
4. the destination stream illuminates;
5. destination card shows the retrieved decision/finding with provenance.

Keep animation smooth, 600–1200ms total, no bouncing.

## Copy voice
Direct, specific, technical, concise.
Prefer: “context”, “project knowledge”, “handoff”, “provenance”, “shared”, “private”, “revision”, “agent”.
Avoid as primary category language: “second brain”, “AI brain”, “magic memory”, “supercharge”, “revolutionary”.

## Signature event
Treat a successful cross-agent context handoff as the core branded event, internally and externally called the **Osmos Moment**.

## Source of truth
- `website/BRAND_GUIDELINES.md`
- `website/tokens.json`
- `website/osmos.css`
- `website/assets/`

If a generated design conflicts with these files, follow these files.