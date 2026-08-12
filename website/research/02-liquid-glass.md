# Liquid Glass — What It Actually Is

Two primary sources, both read directly:

1. **`GetStream/awesome-liquid-glass`** — 8 SwiftUI files demonstrating the material on iOS 26
2. **Apple HIG (2025), "Materials" chapter** — PDF pages 123–128, the governing rules

---

## 1. The finding that changes everything: it is a material, not an effect

The demo repository was expected to contain custom shaders, spring physics, and hand-tuned
animation. **It contains none of that.** All 8 files are 37–65 lines. The complete API surface
across the entire repo is three things:

| API | Occurrences |
|---|---|
| `.glassEffect()` | `LiquidGlassHContainer.swift:32`, `LiquidGlassRoundedFloating.swift:32`, `CustomGlassEffect.swift:24` |
| `.buttonStyle(.glass)` | `LiquidGlassRoundedFloating.swift:41`, `LiquidGlassPlayButton.swift:26,38` |
| **Nothing** | `LiquidGlassJello`, `LiquidGlassTabBar`, `LiquidGlassMenu`, `LiquidGlassToolbarItems` |

Four of the eight demos contain **zero glass API calls**. They are plain `Slider`, `Picker`,
`TabView`, `.toolbar`, and `Menu`. The glass appears because the operating system applies it to
standard components automatically.

### The animations are not what they appear to be

The README advertises "squash, stretch, and jello-like effect." No such animation is authored
anywhere in the source. The *only* animations present are `phaseAnimator` calls that move the
**background image**:

```swift
// LiquidGlassHContainer.swift:15-20 — moves the BACKDROP, not the glass
.phaseAnimator([false, true]) { bgImage, move in
    bgImage.offset(y: move ? -320 : 320)
} animation: { move in .easeInOut(duration: 5) }
```

```swift
// LiquidGlassRoundedFloating.swift:42-47 — slides a glass button across a fixed backdrop
.phaseAnimator([false, true]) { bgImage, move in
    bgImage.offset(x: move ? -84 : 0)
} animation: { move in .easeInOut(duration: 6) }
```

These are **demo rigs**. Their purpose is to force different content to pass behind the glass so
you can observe it refracting in real time. The squash, stretch, and morphing are system behaviors
of the standard controls.

### Why this matters for a website

On Apple platforms, "adopting Liquid Glass" means **using standard components** and getting the
material for free. On the web there is no system to inherit from — we would hand-build every
optical layer ourselves, and maintain it. That inverts the cost/benefit completely and is the
central argument in `design/DESIGN-DIRECTION.md`.

---

## 2. The 2025 rules (HIG Materials chapter, pp. 123–128)

Apple's own guidance is overwhelmingly about **restriction**. Verbatim:

### The layer model

> "Liquid Glass forms a distinct functional layer for controls and navigation elements — like tab
> bars and sidebars — that floats above the content layer, establishing a clear visual hierarchy
> between functional elements and content."

Two material families exist. Liquid Glass is for the **functional layer**. "Standard materials"
(ultraThin / thin / regular / thick) are for the **content layer**.

### The prohibition

> **"Don't use Liquid Glass in the content layer.** Liquid Glass works best when it provides a
> clear distinction between interactive elements and content, and including it in the content layer
> can result in unnecessary complexity and a confusing visual hierarchy."

The single exception: *"controls in the content layer with a transient interactive element like
sliders and toggles"* may take on the appearance while active.

### The budget

> **"Use Liquid Glass effects sparingly.** ... overusing this material in multiple custom controls
> can provide a subpar user experience by distracting from that content. **Limit these effects to
> the most important functional elements in your app.**"

### The two variants

| Variant | Behavior | Use when |
|---|---|---|
| **Regular** | Blurs *and adjusts the luminosity* of background content to maintain legibility. Most system components use this. | Background might cause legibility issues, **or the component has significant text** — alerts, sidebars, popovers |
| **Clear** | Highly translucent; prioritizes visibility of what is underneath | Only over **visually rich backgrounds** — photos, video |

### The dimming rule (a concrete number)

For the Clear variant:

> "If the underlying content is bright, consider adding a **dark dimming layer of 35% opacity**."

Not needed if the underlying content is already dark, or if using AVKit playback controls that
provide their own dimming.

### Standard materials — the content layer

Four thicknesses: **ultraThin, thin, regular (default), thick**. The tradeoff is stated plainly:

> "Thicker materials, which are more opaque, can provide better contrast for text and other elements
> with fine features. Thinner materials, which are more translucent, can help people retain their
> context by providing a visible reminder of the content that's in the background."

### Vibrancy hierarchy

Labels: `label` → `secondaryLabel` → `tertiaryLabel` → `quaternaryLabel`
Fills: `fill` → `secondaryFill` → `tertiaryFill`
Separators: one value.

> "The default level has the highest contrast, whereas quaternary (when it exists) has the lowest."

Hard constraint: **avoid quaternary on Thin and Ultrathin materials — "the contrast is too low."**

### Adaptation is mandatory, even in a single-appearance product

> "Even if your app ships in a single appearance mode, provide both light and dark colors to
> support Liquid Glass adaptivity in these contexts."

The material responds to user settings — Reduce Transparency, Increase Contrast, and a display
preference for the look of Liquid Glass. **Any implementation must degrade gracefully**, because
the user can turn the effect down.

### visionOS — the closest ancestor

> "In visionOS, windows generally use an unmodifiable system-defined material called glass...
> **visionOS doesn't have a distinct Dark Mode setting. Instead, glass automatically adapts to the
> luminance of the objects and colors behind it.**"

This is the purest statement of the idea: the material is *adaptive to an unpredictable backdrop*.
That is precisely the hard problem on the web too.

### Timeline

Change logs in the PDF date the Liquid Glass guidance to **June 9, 2025**. It is roughly one year
old as of this writing (2026-08-12) — mature enough to imitate, new enough that imitating it
loudly reads as trend-chasing.

---

## 3. The optical anatomy (what a browser would have to build)

Decomposed from the HIG description and the observed behavior. **Not yet validated against a real
browser implementation** — the CSS/SVG research was cut short.

| Layer | What it does | Likely web primitive |
|---|---|---|
| Backdrop blur | Softens what is behind | `backdrop-filter: blur()` |
| Luminosity adjustment | Lifts or lowers backdrop brightness to protect legibility — **explicitly named in the HIG for the Regular variant** | `backdrop-filter: brightness() saturate()` |
| Edge refraction | Bends background content inward at the rim — a *lens*, not frosted glass. This is what naive blur misses. | SVG `feDisplacementMap` + displacement map — **unverified, browser support uncertain** |
| Specular highlight | Bright rim where light catches the edge | inset `box-shadow`, gradient border |
| Inner shadow | Depth/thickness | inset `box-shadow` |
| Tint | Optional color | semi-transparent background layer |
| Cast shadow | Separates it from content below | `box-shadow` |

**The key physical insight:** Apple is simulating a *lens or droplet*, not frosted glass. Frosted
glass diffuses uniformly; a lens refracts most strongly at its curved edges. This is why
`backdrop-filter: blur()` alone reads as "2015 glassmorphism" rather than as Liquid Glass — it
reproduces exactly one of seven layers.

**Open question:** whether edge refraction is achievable in Safari/Chrome/Firefox in 2026 at
acceptable performance. This was on the cut research list and needs answering before committing to
any glass in the design.

---

## 4. Verdict for the SAC site

Apple's own rules argue **against** a glass-heavy developer-tool site:

1. Glass belongs to the functional layer. A documentation-and-explanation site is almost entirely
   content layer.
2. Glass needs a visually rich backdrop to be worth anything. Our content is text, code, and
   diagrams — the Clear variant would have nothing to reveal, and the Regular variant over a flat
   background is just a gray box with extra GPU cost.
3. "Limit these effects to the most important functional elements."

**The defensible surfaces are narrow:**
- The sticky navigation bar — genuinely a functional layer floating over scrolling content
- Possibly a floating CTA or a code-block header

**Everything else should be solid.** If we ship glass, it should be so restrained that most
visitors never consciously notice it — which is exactly how Apple ships it.
