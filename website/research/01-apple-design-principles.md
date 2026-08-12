# Apple's Design Principles — The Canon and the Through-Line

Primary source: **Macintosh Human Interface Guidelines (Apple/Addison-Wesley, 1992), Chapter 1,
"Human Interface Principles"** — PDF pages 25–38, read in full. Quotations below are verbatim.

Supporting: **Apple Human Interface Guidelines (2025)**, compiled edition, 915 pp.

---

## 0. Why the 1992 document is still the right source

Apple did something unusual: it wrote its design philosophy down and published it as law, for
outside developers, decades before "design system" was a phrase. That act is itself the first
principle — consistency is only achievable if the rules are *written and shared*.

The 1992 chapter opens by framing the rules as a theory, not a style guide:

> "Having technical knowledge of the Macintosh user interface is a key factor in product design,
> but understanding the theories behind the user interface can help you create an excellent
> product."

And it explicitly refuses to be absolute — an escape hatch most design systems lack:

> "You'll undoubtedly find out that you can't design in accordance with all of the principles all
> of the time. In that type of situation, you'll have to make a decision based on which principle
> or set of principles is most important in the context of the task you're solving."

That is the correct posture for our own site: the principles are a ranking device for tradeoffs,
not a checklist.

---

## 1. The eleven principles

Each below: the 1992 statement, then what it means for a **website** in 2026.

### Metaphors
> "You can take advantage of people's knowledge of the world around them by using metaphors to
> convey concepts and features of your application. Use metaphors involving concrete, familiar
> ideas and make the metaphors plain, so that users have a set of expectations to apply."

Critically, 1992 already warns against literalism:

> "Metaphors in the computer interface suggest a use for something, but that use doesn't define or
> limit the implementation of the metaphor."

**For our site:** SAC needs a metaphor because it is invisible infrastructure. "Shared brain,"
"project memory," "the layer between agents" are all candidate metaphors. Pick **one** and let the
visual language serve it. Do not mix three.

### Direct Manipulation
> "An object on the screen remains visible while a user performs physical actions on the object.
> When the user performs operations on the object, the impact of those operations on the object is
> immediately visible."

**For our site:** the strongest possible demo of SAC is one the visitor can *touch* — type into
one agent panel, watch knowledge appear in the other. Far better than a video of it happening.

### See-and-Point (not remember-and-type)
> "Both paradigms share two basic assumptions: that users can see on the screen what they're doing
> and that users can point at what they see."

**For our site:** never require the visitor to hold something in their head across sections.
Every section re-establishes its own context.

### Consistency
> "Consistency in the interface allows people to transfer their knowledge and skills from one
> application to any other."

1992 names the hardest kind:

> "The most difficult kind of consistency to achieve is matching people's expectations."

**For our site:** developer-tool visitors have strong expectations (code blocks with copy buttons,
dark mode, a docs link in the nav). Violating those to be distinctive costs more than it earns.

### WYSIWYG
> "Don't hide features in your application by using abstract commands. People should be able to see
> what they need when they need it."

**For our site:** if the product has limits — no embeddings yet, SQLite locally, V1 scope — the
site says so. A developer audience punishes discovered omissions far harder than stated ones.

### User Control
> "Allow the user, not the computer, to initiate and control actions. People learn best when
> they're actively engaged."

And the anti-pattern, which reads as a direct warning about autoplay and forced scroll narratives:

> "In other instances, the computer 'takes care' of the user, offering only those alternatives that
> are judged 'good' for the user... This approach mistakenly puts the computer, not the user, in
> control."

**For our site:** no scroll hijacking. No autoplaying audio. Animations the visitor can skip past.

### Feedback and Dialog
> "Keep users informed about what's happening with your product. Provide feedback as they do tasks
> and make that feedback as immediate as possible."

The 1992 text mocks unhelpful errors — *"The computer unexpectedly crashed. ID = 13."* — and asks
for messages that state the actual cause.

**For our site:** every interactive demo needs visible state. Loading, empty, and error states are
part of the design, not an afterthought.

### Forgiveness
> "Forgiveness means that actions on the computer are generally reversible. People need to feel
> that they can try things without damaging the system."

With a sharp diagnostic:

> "Frequent alert boxes are a good indication that something is wrong with the program design."

**For our site:** any interactive demo must be resettable. No dead ends.

### Perceived Stability
> "If people are to cope with this complexity, they need some stable reference points... Note that
> it is the perception of stability that you want to preserve, not stability in any strict physical
> sense."

Also: unavailable actions are *"not eliminated from a display but are merely dimmed."*

**For our site:** persistent nav, consistent section rhythm, a predictable grid. Novelty in the
layout of every section reads as instability.

### Aesthetic Integrity
> "Aesthetic integrity means that information is well organized and consistent with principles of
> visual design."

The operative sentence is about **restraint**:

> "Keep the graphics of the display simple. The number of elements and their behaviors should be
> limited to enhance the usability of the interface."

And a warning that applies directly to decorative tech illustration:

> "Don't use arbitrary graphic images to represent concepts... the meaning may be clear to you, but
> to other people the symbols may appear as something different and distracting."

**For our site:** every diagram must be *readable*, not evocative. Abstract glowing node-graphs are
exactly the arbitrary graphic image this forbids.

### Modelessness
> "Try to create modeless features that allow people to do whatever they want when they want to."

**For our site:** no gate before the visitor can understand the product. No email wall in front of
the explanation.

### Plus two "additional issues"

**Knowledge of Your Audience** — 1992 recommends writing scenarios of a typical day and visiting
actual workplaces. Our equivalent is in `plan/SITE-PLAN.md` §2.

**Accessibility** — present in the 1992 chapter, and now the most heavily codified area of all
(see `03-web-platform-rules.md`).

---

## 2. The style eras

| Era | Years | Character | What drove it |
|---|---|---|---|
| Desktop / Platinum | 1984–1999 | Bitmapped, restrained, grayscale-first | 1-bit and 8-bit displays; the metaphor had to carry the meaning |
| **Aqua** | 2000–2012 | Translucent, glossy, photorealistic, animated | Color displays + GPU compositing made depth cheap |
| **Flat / Deference** | 2013–2024 | Ornament removed, typography and color carry hierarchy | Retina displays; skeuomorphism read as dated |
| **Liquid Glass** | 2025– | Real-time refractive material as the chrome layer | GPU budget to composite live optical effects |

The style reversed twice. The principles did not change once. Anyone who concludes "Apple went
flat, then went back to glossy" has mistaken the surface for the argument.

---

## 3. The through-line — what never changed

**1. Deference: chrome serves content.**
1992: *"Keep the graphics of the display simple."*
2025: *"Don't use Liquid Glass in the content layer."*
The same rule, thirty-three years apart, in different vocabulary.

**2. Depth communicates hierarchy — it is not decoration.**
1992's Perceived Stability asks for a consistent spatial model. 2025's Materials chapter defines a
literal two-layer model (functional layer floating above content layer). Glass is *how you signal
which layer a thing lives on*. Used without that job, it is noise.

**3. Motion explains; it does not decorate.**
1992: *"Animation, when used sparingly, is one of the best ways to show a user that a requested
action is being carried out."* Note "sparingly" and note the *purpose clause*. Every animation
should be answerable to "what did that tell the user?"

**4. Restraint is the mechanism.**
Read the guidance across all eras and it is overwhelmingly phrased as **limits**, not permissions.
"Don't use," "sparingly," "limited to," "avoid." The quality is produced by subtraction.

**5. The interface must be honest about state.**
Feedback, Forgiveness, and WYSIWYG are all one idea: never let the user be wrong about what the
system is doing.

---

## 4. The operative doctrine (with a testable check)

The distilled decision-generators, each with the question to ask during a design review:

| Doctrine | The check |
|---|---|
| Deference to content | *If I removed this treatment, would the content be harder to understand? If no, remove it.* |
| One idea per section | *Can I state this section's single claim in one sentence? If it takes two, split it.* |
| Depth signals hierarchy | *Does this layer/shadow/blur tell the user what floats above what? If not, it's decoration.* |
| Motion explains | *What did that animation teach? If the answer is "it looks nice," cut it.* |
| Typography is the primary tool | *Is the hierarchy legible with all color and imagery removed?* |
| Restraint | *What is the smallest number of elements that still does the job?* |
| Honesty about state | *Are the loading, empty, and error states designed, or assumed away?* |

---

## 5. How teams imitating Apple get it wrong

Observed failure modes, each traceable to a principle above:

- **Glass everywhere.** Applying the material to content surfaces, violating the explicit 2025 rule
  and destroying the hierarchy signal that made it valuable.
- **Motion without meaning.** Scroll-triggered animation on every element; the visitor learns to
  ignore movement entirely.
- **Scroll hijacking.** Directly violates User Control.
- **Thin low-contrast gray text** as a proxy for "refined." Fails both Aesthetic Integrity and WCAG.
- **Arbitrary abstract graphics** — the glowing node-cloud — explicitly named as an anti-pattern in
  1992.
- **Everything centered.** Center alignment reads as elegant for one hero and as structureless for
  a whole page. Apple uses a strong left-aligned grid for anything information-dense.
- **Borrowing the surface without the hierarchy.** The real work is deciding what is most
  important. The visual style is downstream of that decision, and cannot substitute for it.
