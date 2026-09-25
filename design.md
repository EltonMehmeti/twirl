# Design — Vesha

A locked design system for the Vesha app (package `twirl`). Every page redesign
reads this file before emitting code. Do not regenerate per page — extend or
amend this file when the system needs to grow.

Source of the brand: `docs/design/tokens.css` and `docs/design/Provider Onboarding.dc.html`.
The live implementation is `src/twirl/static/vesha.css` (its `:root` block is the
only token block the app loads).

## Genre
Editorial. A fashion rental marketplace: the photographs carry the page, type
is quiet, gold is a signal, not a decoration.

## Macrostructure family

- **Discovery pages** (home `/`, shop `/{slug}`): **Catalogue.** Search sits above
  a uniform 3:4 photo grid; hairline rule above every tile row; no big display;
  no global CTA inside the grid. Home adds a shop index (hairline list, no cards)
  and one typographic "list your clothes" band.
- **Dress page** (`/{slug}/{code}`): **Photographic.** Photos lead (full-bleed swipe
  on phones, large stacked grid on desktop); text is annotation beside them; one
  booking panel is the only boxed element.
- **Content pages** (confirmation, error, legal): **Long Document.** Left-aligned,
  one column, h1 then prose; the booking code is the only boxed element.
- **App pages** (onboarding, shop admin): Workbench — function carries the page.
  They share every token and component rule below; no enrichment.

## Theme
- `--color-paper`       oklch(98.4% 0.004 106)  page surface
- `--color-paper-2`     oklch(95.2% 0.012 92)   app background, quiet fills
- `--color-ink`         oklch(19.1% 0 0)        text, primary outlines, focus
- `--color-ink-soft`    oklch(37.3% 0.011 78)   secondary text
- `--color-muted`       oklch(52.6% 0.017 85)   meta text (≥ 4.5:1 on paper)
- `--color-line`        oklch(90.3% 0.014 93)   hairlines
- `--color-line-strong` oklch(83.9% 0.021 92)   control borders
- `--color-gold`        oklch(79.9% 0.159 80)   accent — buttons, selected size, logo dot
- `--color-gold-hover`  oklch(76.2% 0.156 79)
- `--color-gold-soft`   oklch(93.2% 0.071 89)   calendar bookings, "pending" pills
- `--color-gold-pale`   oklch(96.4% 0.049 92)
- `--color-gold-wash`   oklch(98% 0.025 89)     banners
- `--color-gold-ink`    oklch(54.1% 0.109 87)   link hover (4.8:1 on paper)
- `--color-danger`      oklch(54.3% 0.174 30)
- `--color-danger-soft` oklch(95.5% 0.016 22)
- `--color-good`        oklch(54% 0.105 139)
- `--color-focus`       = ink (17:1 on paper)

Gold never carries text contrast on its own (1.8:1 on paper): text on gold is ink.

## Typography
- Display: Clash Display 600, style normal. Headings and dress/shop names only.
- Body: Hanken Grotesk 400 / 600. Everything else, including form labels,
  table heads, pills, crumbs and footer — **sentence case, no letter-spacing**.
- Mono: system mono. **Only** for booking codes, prices, dates and day numbers.
- Wordmark: Clash Display 600, uppercase, 0.22em — the one uppercase element.
- Display tracking: -0.02em. h1 30px phone / 36px desktop; dress page h1 same.
- No eyebrows. No italic headings. No uppercase mono labels.

## Spacing
Existing px rhythm (4-pt based: 4 · 8 · 12 · 14 · 16 · 18 · 20 · 24 · 28 · 44).
New rules use the same steps.

## Radius
- `--radius-card` 14px — the booking panel, admin surfaces, tables.
- `--radius-photo` 4px — every photograph and photo placeholder.
- Pills and buttons 999px.

## Motion
- `--ease-out` cubic-bezier(0.16, 1, 0.3, 1); `--dur-short` 160ms; `--dur-long` 420ms.
- One hover effect per element: photos zoom 1.03 (tiles only); buttons change
  fill; outlined links darken their border. Nothing lifts.
- `:active` on buttons: translateY(1px), no transition.
- Results fade to .45 opacity while HTMX loads.
- Reduced motion: all transitions off.

## Microinteractions stance
- Silent success — the next page is the confirmation; no toasts.
- Focus: 2px solid `--color-focus`, offset 2px (tiles 4px), shown instantly.
- Inputs: same focus ring, border turns transparent.

## CTA voice
- Primary: gold pill, ink text, 600 weight, verb-first ("Search", "Request this dress").
- Secondary: transparent pill with `--color-line-strong` border.
- Text links: ink with gold underline; hover gold-ink.
- No arrows or ✓ glyphs as icons; pager/crumb arrows (← →) are text, allowed.

## Per-page allowances
- Discovery and dress pages: real photography only; no illustration, no enrichment.
- App pages: no enrichment.
- Content pages: typography only.

## What pages MUST share
- The wordmark + logo mark, header with two links + SQ/EN, one-line footer.
- Gold as the only accent; ≤ 5 % of a viewport outside photos.
- Clash Display + Hanken Grotesk; mono only for codes / prices / dates.
- The CTA voice above.
- Hairlines, not boxes, to separate sections. At most one boxed element per page
  region (search panel, booking panel, booking code).

## What pages MAY differ on
- Macrostructure within the family above.
- Grid density (2 → 3 → 4 columns).

## Exports

### tokens.css
```css
:root {
  --color-paper: oklch(98.4% 0.004 106);
  --color-paper-2: oklch(95.2% 0.012 92);
  --color-ink: oklch(19.1% 0 0);
  --color-ink-soft: oklch(37.3% 0.011 78);
  --color-muted: oklch(52.6% 0.017 85);
  --color-line: oklch(90.3% 0.014 93);
  --color-line-strong: oklch(83.9% 0.021 92);
  --color-gold: oklch(79.9% 0.159 80);
  --color-gold-hover: oklch(76.2% 0.156 79);
  --color-gold-soft: oklch(93.2% 0.071 89);
  --color-gold-pale: oklch(96.4% 0.049 92);
  --color-gold-wash: oklch(98% 0.025 89);
  --color-gold-ink: oklch(54.1% 0.109 87);
  --color-danger: oklch(54.3% 0.174 30);
  --color-danger-soft: oklch(95.5% 0.016 22);
  --color-good: oklch(54% 0.105 139);
  --color-focus: var(--color-ink);
  --color-veil: oklch(98.4% 0.004 106 / 0.92);
  --font-display: "Clash Display", ui-sans-serif, system-ui, sans-serif;
  --font-sans: "Hanken Grotesk", ui-sans-serif, system-ui, sans-serif;
  --font-mono: ui-monospace, "DejaVu Sans Mono", "SFMono-Regular", Menlo, monospace;
  --radius-card: 14px;
  --radius-photo: 4px;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --dur-short: 160ms;
  --dur-long: 420ms;
  --accent: var(--color-gold);
}
```

### Tailwind v4 `@theme`
```css
@theme {
  --color-paper: oklch(98.4% 0.004 106);
  --color-paper-2: oklch(95.2% 0.012 92);
  --color-ink: oklch(19.1% 0 0);
  --color-muted: oklch(52.6% 0.017 85);
  --color-line: oklch(90.3% 0.014 93);
  --color-gold: oklch(79.9% 0.159 80);
  --color-danger: oklch(54.3% 0.174 30);
  --color-good: oklch(54% 0.105 139);
  --font-display: "Clash Display", sans-serif;
  --font-sans: "Hanken Grotesk", sans-serif;
  --radius-card: 14px;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
}
```

### DTCG `tokens.json`
```json
{
  "color": {
    "paper":  { "$value": "oklch(98.4% 0.004 106)", "$type": "color" },
    "ink":    { "$value": "oklch(19.1% 0 0)", "$type": "color" },
    "muted":  { "$value": "oklch(52.6% 0.017 85)", "$type": "color" },
    "line":   { "$value": "oklch(90.3% 0.014 93)", "$type": "color" },
    "accent": { "$value": "oklch(79.9% 0.159 80)", "$type": "color" }
  },
  "font": {
    "display": { "$value": "Clash Display", "$type": "fontFamily" },
    "body":    { "$value": "Hanken Grotesk", "$type": "fontFamily" }
  },
  "radius": {
    "card":  { "$value": "14px", "$type": "dimension" },
    "photo": { "$value": "4px", "$type": "dimension" }
  }
}
```

### shadcn/ui CSS variables
```css
:root {
  --background: 98.4% 0.004 106;
  --foreground: 19.1% 0 0;
  --primary: 79.9% 0.159 80;
  --primary-foreground: 19.1% 0 0;
  --muted: 95.2% 0.012 92;
  --muted-foreground: 52.6% 0.017 85;
  --border: 90.3% 0.014 93;
  --input: 83.9% 0.021 92;
  --ring: 19.1% 0 0;
  --radius: 14px;
}
```
