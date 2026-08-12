# Design Research — Apple Craft Reference

Background research supporting the Osmos website build. **This folder is reference, not
authority.**

## Where this sits in the hierarchy

The source of truth for how Osmos looks and reads is, in order:

1. `../AI_BRAND_CONTEXT.md` — agent-facing implementation rules
2. `../BRAND_GUIDELINES.md` — full brand system
3. `../tokens.json` / `../osmos.css` — the actual values
4. `../WEBSITE_PLAN.md` — information architecture, content, funnel, roadmap
5. **this folder** — *why* certain craft decisions are right, and the outside standards we hold
   the build to

**If anything here conflicts with the brand files, the brand files win.** These documents were
written before the Osmos brand system was read, and they are kept for their evidence, not their
conclusions about art direction.

## Contents

| File | What it gives you |
|---|---|
| `00-sources-and-provenance.md` | Every source cloned, downloaded, and read — with licenses and reproduction steps |
| `01-apple-design-principles.md` | The canonical Apple principles (1992 HIG, verbatim) and the through-line to 2026 |
| `02-liquid-glass.md` | What Liquid Glass actually is, the 2025 rules governing it, and why we should barely use it |
| `03-web-platform-rules.md` | Verified WCAG 2.2 / responsive / performance thresholds the build gets audited against |
| `../scripts/fetch-sources.sh` | Re-downloads all sources locally (nothing is vendored) |

## What this research changed

Three conclusions that survived contact with the Osmos brand system, and that the build should
honor:

**1. Almost no glass.** Apple's own 2025 guidance says *"Don't use Liquid Glass in the content
layer"* and *"use Liquid Glass effects sparingly."* A developer-tool site is nearly all content
layer. This converges exactly with `BRAND_GUIDELINES.md` — *"no glassmorphism overload"* — and with
the anti-pattern list in `WEBSITE_PLAN.md` §21. **The defensible surface is the sticky nav and
essentially nothing else.**

**2. Restraint is the mechanism, and the brand already encodes it.** Apple's guidance across every
era is phrased as limits, not permissions. Osmos's core rule — *"The interface is calm and neutral;
color appears when knowledge moves"* — is the same idea expressed as a color policy. The flow
gradient is Osmos's equivalent of Apple's material: powerful precisely because it is rationed.

**3. Motion must explain.** The 1992 HIG already said animation should be used *"sparingly"* and
to show *"that a requested action is being carried out."* The Osmos Moment animation is the ideal
case — it is the product argument rendered as motion. Everything else on the page should hold
still.

## Naming note

These documents predate the brand and refer to the product as **SAC** / Shared Agent Context. That
remains the repository name, the service name, and the MCP tool prefix (`sac_*`). **Osmos** is the
public brand. Both are correct in their own context.

## What was deliberately not researched

Cut for time, sources are downloaded if any becomes blocking:

- Whether edge-refraction glass is achievable across browsers in 2026 *(moot unless we ship glass
  beyond a blurred nav — which the conclusion above argues against)*
- apple.com's scroll choreography and video-scrubbing implementation
- Developer-tool comparables studied properly: Linear, Vercel, Stripe, Raycast
- The 1987 / 2001 / 2008 HIG lineage in detail — only the 1992 canon was read

An earlier draft of this folder also contained a competing site plan and art-direction document.
Both were **removed** — `../WEBSITE_PLAN.md` and `../BRAND_GUIDELINES.md` supersede them, and two
conflicting plans is worse than one.
