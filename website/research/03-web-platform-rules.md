# Web Platform Rules — The Non-Negotiables

Source: **`ehmo/platform-design-skills` → `skills/web/SKILL.md`** (1,454 lines, MIT licensed).
Built from WCAG 2.2, MDN, and modern web platform APIs.

All numbers below were **read directly from the source file** and are cited by line. This is the
most directly applicable of the three researched repositories — it is the rulebook our site will
actually be audited against.

---

## Structure and priority

The rulebook assigns explicit priority levels. Two sections are marked **[CRITICAL]**:

| § | Section | Priority |
|---|---|---|
| 1 | Accessibility / WCAG | **CRITICAL** |
| 2 | Responsive Design | **CRITICAL** |
| 3 | Forms | HIGH |
| 4 | Typography | HIGH |
| 5 | Performance | HIGH |
| 6 | Animation and Motion | MEDIUM |
| 7 | Dark Mode and Theming | MEDIUM |
| 8 | Navigation and State | MEDIUM |
| 9 | Touch and Interaction | MEDIUM |

Note the ordering: accessibility and responsiveness outrank typography and performance. This
matches Apple's own posture — the HIG treats accessibility as a foundation chapter, not an
appendix.

---

## Verified thresholds

These are the hard numbers. Anything we build gets checked against them.

### Color contrast (`SKILL.md:177-179`)

| Content | Minimum ratio |
|---|---|
| Normal text (< 24px, or < 18.66px bold) | **4.5:1** |
| Large text (≥ 24px, or ≥ 18.66px bold) | **3:1** |
| UI components and graphical objects | **3:1** |

This is the rule that kills the "elegant thin gray text" instinct. It also governs any text placed
over a translucent or glass surface — where the backdrop is variable, contrast must be guaranteed
at the *worst case*, not the average.

### Focus indicators (`SKILL.md:128`)

> "WCAG 2.2 requires focus indicators to have a minimum area of the perimeter of the component
> times 2px, with **3:1 contrast** against adjacent colors."

### Touch targets (`SKILL.md:389`)

- **44 × 44 CSS px** minimum (WCAG SC 2.5.5, Level AAA)
- SC 2.5.8 (Level AA) requires only **24 × 24 px**
- At least **24px spacing** between adjacent targets

Target 44×44 — it matches Apple's own platform minimum, so it is free consistency.

### Typography (`SKILL.md:613, 631-640`)

- Body line-height **at least 1.5** (SC 1.4.12)
- Paragraph spacing **at least 2× font size**
- Line length **~75 characters maximum** — `max-width: 75ch`, or `40rem` for roughly 65–75ch
  depending on the font

### Responsive (`SKILL.md:381-383`)

Content-based breakpoints, not device-based:

```css
@media (min-width: 30rem)  { /* ~480px:  single column gets cramped */ }
@media (min-width: 48rem)  { /* ~768px:  room for 2 columns */ }
@media (min-width: 64rem)  { /* ~1024px: room for sidebar + content */ }
```

Fluid sizing via `clamp()` (`SKILL.md:335, 340`):

```css
font-size: clamp(1.75rem, 1.2rem + 2vw, 3rem);
padding:   clamp(1.5rem, 4vw, 4rem);
```

### Hard prohibitions

- **Never** `maximum-scale=1` or `user-scalable=no` — breaks pinch-to-zoom (SC 1.4.4)
  (`SKILL.md:418`)
- **Never** `<div onclick>` when `<button>` exists — use native interactive elements, which are
  keyboard-accessible by default (`SKILL.md:83`)
- **Always** specify image `width` and `height` to prevent layout shift / CLS (`SKILL.md:708`)

### Semantic HTML

The rulebook opens with semantics, and the framing is worth keeping: semantic structure provides
"free accessibility, SEO, and reader-mode support." The named anti-pattern is **div soup**.

Elements it expects us to use correctly: `<main>` (one per page), `<nav>`, `<header>`, `<footer>`,
`<article>`, `<section>` (thematic grouping *with a heading*), `<aside>`, `<figure>`/`<figcaption>`,
`<details>`/`<summary>`, `<dialog>`, `<time>`, `<mark>`, `<address>`, and the HTML5 `<search>`
landmark.

---

## Where this converges with Apple

Three rules appear independently in both the HIG and the web rulebook, which makes them the safest
possible foundations:

1. **Respect user settings.** `prefers-reduced-motion`, `prefers-contrast`, `prefers-color-scheme`
   on the web; Reduce Transparency / Increase Contrast / appearance mode on Apple platforms. Both
   treat these as mandatory, not optional enhancements.
2. **Contrast is not negotiable.** Apple's vibrancy hierarchy exists specifically so text stays
   legible over variable materials; WCAG states the same requirement as a number.
3. **Motion must be meaningful and skippable.** §6.5 is literally titled "Meaningful Motion Only,"
   which is the 1992 HIG's *"animation, when used sparingly"* restated for the web.

---

## Caveat on the agent-generated extraction

A 64 KB automated extraction of this rulebook exists at
`scratchpad/research/findings/02-pds-web-rules.md`. It was produced by a subagent and **has not
been verified**. Every number in *this* document was read from the source file directly and is
line-cited. Treat the extraction as a lead; treat `SKILL.md` as the authority.
