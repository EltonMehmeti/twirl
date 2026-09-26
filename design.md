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
- `--color-shadow`      oklch(19.1% 0 0 / 0.18)  the one floating element (the "see results" bar)

Gold never carries text contrast on its own (1.8:1 on paper): text on gold is ink.

## Typography
- Display: Clash Display 600, style normal. Headings and dress/shop names only.
- Body: Hanken Grotesk 400 / 600. Everything else, including form labels,
  table heads, pills, crumbs and footer — **sentence case, no letter-spacing**.
- Mono: system mono. **Only** for booking codes, prices, dates and day numbers.
  Exception: on dress tiles the price leads, in Clash Display 600 21px (tabular);
  the dress name sits under it in Hanken 600 14px, one line, ink-soft.
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
- Easing: `--ease-out` cubic-bezier(0.16, 1, 0.3, 1) for arriving, `--ease-exit`
  (0.4, 0, 1, 1) for leaving. Durations: `--dur-press` 100ms (press release),
  `--dur-short` 160ms (fills, fades, hints, exits), `--dur-base` 240ms (entrances,
  sheets, bars, step slides), `--dur-long` 420ms (hover only, never on a tap),
  `--dur-reveal` 640ms (the unveil only). Distance `--rise-sm` 4 / `--rise` 8 /
  `--shift` 16px; press `--press` .97 buttons, `--press-lg` .98 tiles, pills .96.
- The tap path animates only transform and opacity (block-size only for small
  disclosures: "More filters", the Decline reason).
- The one authored moment: dress photos unveil top-down (clip-path, like a garment
  bag being unzipped) while the photo settles from 1.08 to 1; name, price and shop
  rise in after. 60ms stagger, capped at 8 tiles. Runs on arrival and after every
  search (`.v-grid--unveil`, `--i` per tile). Renter grids only.
- Home h1 and lede rise 8px on arrival. The logo swings on its hook once on the
  home page and on hover.
- One hover effect per element: photos zoom 1.03 (tiles only); dress and shop
  names get a 2px gold underline drawn from the left; buttons change fill;
  outlined links darken their border. Nothing lifts.
- `:active`: buttons press to .97 and tiles to .98 instantly, then ease back over
  100ms. No grey tap flash. Hover effects apply only where the device can hover.
  Date and category pills fill over 160ms and press to 0.96.
- Feedback: a plain form's button runs the ink loading line while the next page
  loads and ignores a second tap. Errors rise 4px; touched invalid fields turn
  their border red; the first bad field gets focus. The availability answer dims
  while checking, rises in, and taken sizes get a struck line. "Copy link" turns
  into "Copied" in place (the one success that has no next page).
- Navigation: onboarding steps slide 16px the way you are going (back slides the
  other way) and the progress bar grows; the shop's current-tab pill glides to the
  new tab. On phones a Request bar (ink pill, the one shadow) rises on the dress
  page while the booking panel is below the screen.
- Loading and content: photos fade in once decoded, with a paper sheen only after
  300ms; uploads fill their slot from the bottom with real progress; a removed
  photo fades and shrinks before the list updates; the booking code's characters
  rise 30ms apart. The dress gallery shows its position as a hairline tied to the
  swipe. The customer contact sheet slides up and drags down to close.
- Photo viewer (`viewer.js`, PhotoSwipe): a dress photo grows from where it sits to
  full screen on paper over 240ms and shrinks back onto the photo you ended on over
  160ms; it fades instead when that photo is off screen, in native full screen, or
  under reduced motion. Pinch, double-tap, click or wheel zooms; swipe or ← → moves;
  swipe down, Close, Esc or Back closes. Its controls are words, like everywhere.
- Shop screens: after an action on a booking only the status pill and the history
  move. The SMS code fills six hairline slots and sends itself on the sixth digit.
  A size that becomes taken on the new date turns the select red with a hint. The
  calendar keeps the dress column fixed, opens on today and fades its "more" edge
  as Sunday arrives; weeks slide like onboarding steps. Today's counts jump to
  their lane (gold underline for a moment), and the board refreshes every 60s
  while visible, new rows rising with a gold wash. Walk-in codes resolve under
  the field as you type.
- While HTMX loads: results fade to .45 and a gold line runs under the results
  heading. "More filters" slides open where the browser can animate to auto height.
- Reduced motion: distance and scale tokens go to zero, so nothing moves or
  scales; no unveil, swing, sheen or strike animation; the loading lines stay
  still; colour and opacity feedback, upload progress and the gallery position
  (both are data) remain.

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
  --color-shadow: oklch(19.1% 0 0 / 0.18);
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
