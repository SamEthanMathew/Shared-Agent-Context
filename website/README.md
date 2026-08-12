# Osmos Website Brand System

This folder is the website-facing source of truth for the Osmos visual identity, implementation rules, and public-site plan.

## Read order

1. [`WEBSITE_PLAN.md`](WEBSITE_PLAN.md) — researched website architecture, homepage wireframe, setup funnel, videos, CTAs, analytics, and implementation roadmap
2. [`AI_BRAND_CONTEXT.md`](AI_BRAND_CONTEXT.md) — concise instructions for coding agents
3. [`BRAND_GUIDELINES.md`](BRAND_GUIDELINES.md) — full design principles and brand rules
4. [`tokens.json`](tokens.json) — machine-readable design tokens
5. [`osmos.css`](osmos.css) — CSS variables and starter utilities
6. [`assets/`](assets/) — canonical logo assets

## Core rule

> **The interface is calm and neutral; color appears when knowledge moves.**

The Osmos mark uses a white horizontal connective axis behind five violet-to-cyan streams. The axis represents the persistent shared project layer. The colored streams represent independent people, agents, models, tools, and knowledge sources converging through the same project understanding.

## Website implementation

Use this folder before creating or modifying the Osmos landing page, setup experience, dashboard, docs site, launch page, social cards, product screenshots, videos, or other website-facing material.

The primary website conversion path defined in `WEBSITE_PLAN.md` is:

```text
visitor -> /setup -> project -> first agent -> teammate/second agent -> first Osmos Moment
```

The older `branding/` directory is retained for continuity, but new website implementation should read from `website/`.