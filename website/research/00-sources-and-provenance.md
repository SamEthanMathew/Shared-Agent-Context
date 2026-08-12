# Sources & Provenance

Complete record of what was cloned, downloaded, read, and produced during the design research
session on 2026-08-12.

---

## 1. Repositories cloned

All three were cloned to a scratch directory **outside this repo**, not vendored in.

Scratch root (session-local, ephemeral):
```
C:\Users\samet\AppData\Local\Temp\claude\C--Users-samet-Shared-Agent-Context\
  19976f72-2111-4c0e-be9b-3dc64bfa8837\scratchpad\research\
```

| Repository | Contents | License | Vendorable? |
|---|---|---|---|
| `GetStream/awesome-liquid-glass` | 8 SwiftUI files + 6 GIF previews demonstrating iOS 26 Liquid Glass | **No LICENSE file → all rights reserved** | **No** |
| `gingerbeardman/apple-human-interface-guidelines` | Archive of 40 published Apple HIG PDFs, 1980–2014 | Apple copyright; archival collection | **No** |
| `ehmo/platform-design-skills` | 450+ distilled design rules across 8 platforms + compiled `Apple_HIG.pdf` | **MIT** | Yes, with attribution |

### Clone notes

- `awesome-liquid-glass` — cloned clean. Small (19 files).
- `apple-human-interface-guidelines` — a full clone **times out**; the repo is ~450MB of PDFs
  (individual files up to 68MB). Do not clone it whole. Fetch individual PDFs by raw URL instead
  (see `scripts/fetch-sources.sh`).
- `platform-design-skills` — cloned clean, ~2.4MB, dominated by its bundled `Apple_HIG.pdf`.

---

## 2. PDFs downloaded individually

From the `gingerbeardman` archive, selected for the design-principle lineage:

| File | Size | Why |
|---|---|---|
| `1992 Macintosh Human Interface Guidelines.pdf` | 3.9 MB | **The canonical principles chapter.** Primary source. |
| `1987 Apple Human Interface Guidelines - The Apple Desktop Interface.pdf` | 11.8 MB | Origin of the desktop metaphor |
| `2001 Aqua Human Interface Guidelines.pdf` | 7.5 MB | The photorealistic/translucent era |
| `2008-11 iPhone Human Interface Guidelines.pdf` | 9.4 MB | Touch and the return of direct manipulation |
| `iPhone Human Interface Guidelines for Web Applications.pdf` | 2.7 MB | Apple's own guidance for **web** — directly on-topic |

Bundled separately with `platform-design-skills`:

| File | Pages | Why |
|---|---|---|
| `Apple_HIG.pdf` | **915** | Compiled **current (2025)** HIG. Source of all Liquid Glass rules cited. |

---

## 3. What was actually read

Primary sources read directly, not summarized by a subagent:

| Source | Extent |
|---|---|
| All 8 `awesome-liquid-glass` Swift files | **Complete**, line by line |
| `1992 Macintosh HIG` Chapter 1, "Human Interface Principles" | **Complete** — PDF pages 25–38 |
| `Apple_HIG.pdf` "Materials" chapter | **Complete** — PDF pages 123–128 |
| `Apple_HIG.pdf` App Icons / Color, Liquid Glass mentions | Partial — pages 42, 48, 52; 29 pages mention Liquid Glass |
| `platform-design-skills/skills/web/SKILL.md` | Section structure (all 9 sections, 70 headings) + verified numeric thresholds |
| `platform-design-skills/README.md` | Complete |

### Extraction method

PDF page rendering was unavailable (`pdftoppm` / poppler not installed on this machine).
Text was extracted with **pypdf** instead, which was installed into the system Python during
this session:

```bash
python -m pip install pypdf
```

Verbatim extracts were written to the scratch directory (not committed — see §5):

- `hig-pdfs/1992-principles.txt` — Chapter 1 in full
- `hig-pdfs/2025-materials.txt` — Materials chapter in full

---

## 4. Research that was started and deliberately stopped

A 12-agent research workflow was launched, then **stopped early** at the user's direction to
prioritize speed over exhaustiveness. Only one agent completed before the stop:

- `02-pds-web-rules.md` (64 KB) — a full extraction of the web platform rulebook, written to
  `scratchpad/research/findings/`. **Agent-generated and unverified** — treat as a lead, not a
  citation. The underlying `SKILL.md` is the authority.

**Not researched** (scope consciously cut, sources are downloaded and available):

- How apple.com marketing pages are constructed — scroll choreography, video scrubbing, grid
- CSS/SVG techniques for reproducing Liquid Glass in a browser
- Concrete design tokens — type scale, tracking tables, system color hex values, easing curves
- The 1987 / 2001 / 2008 historical lineage in detail (only the 1992 canon was read)
- Developer-tool comparables (Linear, Vercel, Stripe, Raycast)

These are the natural next research increment if the site design needs them.

---

## 5. What was added to this repository

Only original writing. Full list:

```
website/research/
├── README.md                             (index; hierarchy vs the brand files)
├── 00-sources-and-provenance.md          (this file)
├── 01-apple-design-principles.md
├── 02-liquid-glass.md
└── 03-web-platform-rules.md
website/scripts/
└── fetch-sources.sh
```

Plus one line appended to `.gitignore`:

```
website/research/source-extracts/
```

Two earlier drafts — a competing site plan and an art-direction document — were **removed** during
reconciliation with the Osmos brand system. `website/WEBSITE_PLAN.md` and
`website/BRAND_GUIDELINES.md` supersede them.

**No source material was copied in.** Quotations in these documents are short, attributed, and
used for internal design reference. If any of this folder is ever published, re-check the
quotations against fair-use limits — Apple's HIG text is copyrighted.

---

## 6. Reproducing the sources

```bash
bash website/scripts/fetch-sources.sh
```

Downloads all three repositories and the five historical PDFs into
`website/research/source-extracts/`, which is gitignored. Requires `git`, `curl`, and
`python -m pip install pypdf` for text extraction.
