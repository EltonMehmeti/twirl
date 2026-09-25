# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Renters (primary).** Women aged about 22–40 in Kosovo (Ferizaj and Prishtinë first)
  who go to several weddings, engagements and henna nights each summer and want a
  different dress each time. Also diaspora renters in Germany, Switzerland and Austria
  who arrive shortly before a family wedding and want a dress waiting for them.
  Their job: find a dress that is free on *their* event date in *their* size, reserve
  it without visiting four shops, try it on and pick it up once. They are on
  mid-range Android phones and iPhones, and live in Instagram, WhatsApp and Viber.
- **Listers.** Dress rental salons (owner aged about 35–55, 150–400 dresses, family
  staff, busiest May–September) and individuals with a handful of dresses worn once.
  Their job: get bookings without answering "is it free on the 19th, size 38?" in
  DMs all day, and never double-book a dress.
- **Shop staff.** Seasonal or family helpers who record walk-in bookings and check
  today's pickups on the shop phone.
- **Platform admin.** The solo founder: approves shops, sets the verified badge,
  resolves conflicts.

## Product Purpose

Vesha lets someone in Kosovo pick their event date and see only the dresses that
are actually free that day, across shops, then request one in a minute. The shop
confirms, and the renter pays and picks up in the shop. Success means renters come back to
Vesha for every event instead of messaging shops one by one, and listers keep their
calendars true because Vesha is where the bookings come from.

## Positioning

**Renter marketplace first** (founder decision 2026-09-26, replacing the spec's
"shop calendar first" pitch). The mechanism a directory or an Instagram page cannot
copy: availability is per physical dress and per date, including the shop's pickup,
return and cleaning days. A dress shown as free on a date really is free, and
double-booking is prevented by the database. The shop tools (calendar, walk-ins,
today's pickups) exist so that this promise stays true.

## Operating Context

- Renter flow: home → pick event date (plus size, city, category, price) → dress
  page with sizes free on that date → request with name and phone → confirmation
  code; the shop confirms or declines; the renter messages the shop on WhatsApp or Viber.
- Shops confirm requests, record walk-ins and phone bookings, and see today's pickups and
  returns on a phone in the shop, often mid-fitting.
- Language: Albanian (`sq`) is the default, English (`en`) is secondary (mainly for the
  diaspora). Shop-entered text is Albanian only. Prices are shown as `55 €` in
  Albanian and `€55` in English. Phones are shown locally as `049 123 456`.
- Seasonality: demand peaks May–September; the matura season (April) is the planned
  renter launch.

## Capabilities and Constraints

- Built: date-first search with per-item availability; request-and-confirm booking;
  shop onboarding for salons and individuals (phone code sign-in); shop dashboard,
  calendar, walk-ins, dress editor; booking code confirmation; SQ/EN.
- Stack: FastAPI, Jinja2 + HTMX (server-rendered), PostgreSQL, deployed on Render with
  Neon. No client framework.
- Terminology: *style* = the dress design shown to renters; *item* = one physical
  piece in one size. Booking statuses: hold, pending shop, confirmed, picked up.
- Money: the renter pays the shop in person today; Vesha takes no payment. **Planned:**
  a renter reservation fee paid to Vesha through a local bank gateway (the spec's €3
  for a shop's own customers, €5–€20 for customers Vesha brought), deducted in the shop. The gateway is
  not chosen; do not show fees in the UI until it exists.
- Not built / open: SMS or WhatsApp provider (codes currently echoed on staging),
  renter accounts, reviews, deposits, ID verification, the domain.
- Individuals can list, but Vesha does not handle damage disputes or handover between
  individuals.

## Brand Commitments

- Name in the UI: **Vesha** (the code package and repo are `twirl`).
- The existing logo mark (`src/twirl/templates/_logo.html`) and brand fonts and colours
  from `docs/design/`, which were the founder's required design source for the front end.
- Voice: plain, direct Albanian; honest about what is not built yet ("No payment
  online: the shop confirms, you pay when you pick it up").

## Evidence on Hand

Nothing real yet: no signed shops, no real dress photos, no testimonials, no user
counts, no social accounts. Staging data is test data. Future work must use honest
empty states and must not invent shops, reviews, numbers or photos.

## Product Principles

1. **The date comes first.** Every renter surface starts from "free on your date"; a
   dress that isn't free is never shown as available.
2. **Truth over reach.** A shorter list of dresses that are really free beats a long list that
   turns out wrong in the shop.
3. **No payment surprises.** Say who is paid, when and where on every step
   that leads to a booking.
4. **The shop phone is the workplace.** Shop tools must work one-handed on a phone during
   a fitting.
5. **Albanian first, diaspora-ready.** Albanian is the default everywhere; English must be
   complete, not an afterthought.

## Accessibility & Inclusion

WCAG 2.1 AA as a practical target: contrast ≥ 4.5:1, touch targets ≥ 44 px, a label on
every input, visible focus states, alt text on every photo, a keyboard-operable calendar,
status never shown by colour alone, and `prefers-reduced-motion` respected. Test once
with TalkBack.
