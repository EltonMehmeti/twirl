# Provider Onboarding (Vesha design) Implementation Plan

> **For agentic workers:** executed inline with superpowers:executing-plans. Each task is test-first and ends in a commit.

**Goal:** A provider (salon or individual) goes from "who are you" to a live listing in one flow, following the Claude Design file `docs/design/Provider Onboarding.dc.html`, on top of the existing backend.

**Architecture:** Server-rendered wizard under `/listo`, one URL per step, state kept in the database (draft shop, draft style, photos, blocks) plus three session keys (chosen path, pending phone, draft style id). Every step is resumable and guarded: a step you have not reached redirects to the furthest reachable one. Photo slots upload immediately with HTMX. A design-system stylesheet (`static/vesha.css`) carries the design tokens and the two brand fonts extracted from `tokens.css`.

**Design source:** `docs/design/Provider Onboarding.dc.html`, `docs/design/tokens.css` (the runtime `support.js` is not used).

## Middle-ground decisions (founder asked for the best mix of design and spec)

| Topic | Design says | We build | Why |
|---|---|---|---|
| Brand | "Vesha" | UI brand "Vesha" via `TWIRL_BRAND_NAME`; code package stays `twirl` | The design is the newest naming signal; one setting to change back |
| Paths | Individual and salon | Both, as `shops.kind` = `individual` / `salon` | Cheap in the data model; the fork is the design's core |
| Deposits | 48 h refundable hold (individual), 30% online (salon), Vesha holds money | No money shown or promised. Panels say how the renter pays (at handover / in the salon) | No payment gateway exists; spec says the platform never holds money |
| "Si në foto" guarantee | Vesha refunds the deposit | Provider confirms the item is delivered as pictured; acceptance timestamp + version stored | Keeps the promise, drops the money we can't move |
| Verification | Phone + SMS code | Phone + 6-digit code, 5 min expiry, 3 attempts, resend after 30 s, 5 sends/hour. SMS sender is pluggable; until a provider is configured codes are logged, and `TWIRL_SMS_DEV_ECHO=true` shows them on screen in development | Design flow kept; provider choice is a later task |
| Login afterwards | not shown | `/login/telefoni` phone-code login for providers | Providers have no password |
| ID + selfie step | optional, off by default | Not built | Off by default in the design; storing ID documents needs a legal review |
| Going live | Live at once, salon badge after check | Live at once. Admin can suspend; admin sets `verified_at` to show "Verified salon". Admin gets a Telegram alert for each new listing | Matches design, keeps a moderation lever |
| Categories / sizes | 5 categories, sizes 34–46 + "Me masë" | New `styles.category`; size value `CUSTOM` shown as "Me masë". Individual picks one size, salon picks every size in stock (one item per size) | One physical dress for individuals |
| Price | "Qera për 3 ditë" | Price per rental, hint explains pickup 2 days before and return the day after (the shop's rental rules) | Accurate to the booking engine |
| Busy dates | One demo month | Current and next month, past days disabled; stored as block bookings on every item | Reuses the engine's blocks |
| Desktop/Telefon toggle | preview control | Dropped; layout is responsive (rail on ≥900 px, progress bar below) | It is a design-tool control |
| Copy | Albanian | English msgids with Albanian translations taken from the design | Keeps the i18n test green |

## Tasks

1. **Design system:** extract fonts to `static/fonts/`, `static/vesha.css`, brand setting, logo partial, rename brand in notifications and WhatsApp text.
2. **Schema:** `shops.kind/verified_at/terms_accepted_at/terms_version/onboarding_completed_at`, `users.phone_verified_at`, `styles.category/internal_ref`, `phone_codes` table; migration 0005.
3. **Phone codes + SMS + phone login:** `twirl/otp.py`, SMS sender on `app.state`, `/login/telefoni` and `/login/kodi`.
4. **Onboarding service:** `twirl/onboarding.py` (slugs, provider save + hours, draft style, dress details, price + busy dates, publish, calendar grid, flow state).
5. **Wizard: fork, phone, code.**
6. **Wizard: profile (individual) and salon.**
7. **Wizard: item with HTMX photo slots.**
8. **Wizard: price + calendar, review + publish, done.** Admin: kind + verified in ShopAdmin; storefront "verified salon" badge.
9. **Albanian translations, screenshots at desktop and phone width, manual run.**
