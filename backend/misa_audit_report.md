# MISA Affiliate / Distribution Layer — Audit Report

**Date:** 21 September 2026  
**Scope:** Current codebase at `d:\work\brands` (Django backend + Next.js frontend).  
**Instruction:** Inspect only. Do not implement. Do not rebuild Studio. Do not delete working functionality.

This report is the technical source of truth for the next implementation phases. It is based on the live call graph (models → URLs → views → frontend consumers), not on assumed unused code.

---

## Executive snapshot

MISA today is a **working brand-owner AI product-video studio** with brand/product CRUD, a thin agent login/profile stub, and a **brand-only product share counter**. It is **not** yet an affiliate distribution, commission, wallet, or team-management platform.

| Layer | Status |
|-------|--------|
| AI Studio (Brief → Export) | Complete and must stay intact |
| Brand / product catalog | Complete |
| Agent register / login / profile stub | Partial |
| Product share links + open/share counters | Partial (no agent attribution) |
| Teams, invites, join requests | Missing |
| Per-agent tracking links + event log | Missing |
| Commission ledger + platform fee | Missing (`Product.commission` is a % field only) |
| Wallet / ledger / withdrawals | Missing |
| Platform admin finance UI | Missing (Django admin CRUD only) |
| Real social posting | Missing (authorization record only) |

**Hard constraint for all later work:** keep `/brand/studio`, `/api/ai/*` director flow, `VideoProject` / `Scene` / `VideoAsset` / `StyleRecipe`, and existing brand product CRUD unchanged in behavior.

---

## Source inventory (verified)

### Django apps

`accounts`, `agents`, `brands`, `ai` plus `django_q` and DRF token auth.  
`AUTH_USER_MODEL = accounts.User`. Database is **SQLite** (`backend/db.sqlite3`). django-q **1 worker**.

### 15 first-party models (all registered in admin)

| App | Model | Role today |
|-----|--------|------------|
| accounts | `User` | `agent` / `producer` role; superuser impersonation |
| agents | `AgentProfile` | 1:1 bio stub |
| brands | `Category` | Brand category |
| brands | `Brand` | Owned 1:N by producer User |
| brands | `Product` | Catalog; `price` Decimal; `commission` **percentage 0–100** |
| brands | `ProductImage` | Product photos |
| brands | `ProductDemoVideo` | Demo clips |
| brands | `ProductShareLink` | **1:1 per product**; `code`, `share_count`, `open_count` |
| ai | `MerchantPreference` | Studio language/style defaults |
| ai | `VideoProject` | Studio project; FK product + owner User |
| ai | `Scene` | 5-scene storyboard clips |
| ai | `VideoAsset` | Generated media files |
| ai | `VideoProjectVersion` | Snapshots |
| ai | `StyleRecipe` | Bulk style keys |
| ai | `UsageRecord` | AI provider cost log (not a wallet) |
| ai | `SocialPost` | TikTok/IG/FB **authorization intent** |

### Frontend routes (19 pages)

Brand workspace: `/brand/studio`, `/brand/videos`, `/brand/brands`, `/brand/products`, `/brand/agents` (placeholder), `/brand/profile`.  
Agent: `/login`, `/register`, `/dashboard` (stub).  
Superuser: `/choose-account`.  
Public: `/`, `/about`, `/help`, `/contact`, `/privacy`, `/terms`.  
Share: **no React page** — Next rewrite `/s/:code` → Django `ProductShareRedirectView`.

---

## Frontend → API → service → model map

### Brand Studio (must not break)

```
/brand/studio
  → GET  /api/brands/, /products/, /categories/
  → GET  /api/ai/preferences/, /videos/, /styles/, /usage/
  → POST /api/ai/video/creative-brief/
  → POST /api/ai/video/{id}/concepts/ → select-concept → timeline
  → POST /api/ai/video/{id}/generate/   (django-q job)
  → POST QA / amendments / correct / approve / export / publish
  → models: VideoProject, Scene, VideoAsset, StyleRecipe, UsageRecord, SocialPost, Product, Brand
```

### Brand catalog + current share

```
/brand/products
  → CRUD /api/brands/products/
  → POST /api/brands/products/{id}/share/   ProductShareView
        → ProductShareLink (OneToOne Product)
  → GET  /s/{code}/                         ProductShareRedirectView
        → open_count += 1; 302 to Product.product_url
```

### Agent surface (almost empty)

```
/register → POST /api/agents/register/  → User + AgentProfile
/login    → POST /api/agents/login/     → Token
/dashboard → no API (local profile display)
GET /api/agents/me/ exists (IsAgent) but UI uses GET /api/auth/me/ instead
```

### Superuser acting

```
Headers X-Acting-User + X-Acting-Brand
  → accounts/authentication.py TokenActingAuthentication
  → skipped on /api/auth/me/, logout, workspaces
```

### Legacy AI endpoints (tested, not used by current Studio UI)

`POST /api/ai/product/analyze/`, `reference/analyze/`, `brief/generate/`, `script/generate/`, `video/generate/`, `video/draft/`, `transcribe/`, `video/concepts/` (no pk).  
**Do not delete.** Tests in `backend/ai/tests/test_studio.py` depend on them. Studio uses the director path instead.

---

## A. Existing functionality that can be reused

1. **User + roles** — `accounts.User.Role.AGENT` / `PRODUCER`; login split at `/api/agents/*` vs `/api/brands/*`.
2. **Permissions scaffolding** — `IsAgent`, `IsBrandOwner`, `IsSuperuser` in `accounts/permissions.py`. Superuser bypass via `can_choose_account`.
3. **Token auth + impersonation** — `TokenActingAuthentication`; frontend `lib/api.ts` already injects acting headers.
4. **Brand ownership** — `Brand.owner` → User; products scoped by `brand__owner=request.user` (+ acting brand filter).
5. **Product catalog** — CRUD, images, demo videos, `product_url` destination, Decimal `price`.
6. **Share code generator** — `ProductShareLink.generate_code()` pattern (random 10-char unique).
7. **Public redirect + Next rewrite** — `/s/<code>/` AllowAny, no auth; `frontend/next.config.ts` rewrites.
8. **Counter increment pattern** — `F("share_count") + 1` / `F("open_count") + 1` (SQLite-safe atomic update).
9. **Video content as distribution payload** — `VideoProject.export_file` / `final_video` / `preview_video` after Approve → Export. Agents should link to **exported** projects, not drafts.
10. **Django admin** — every current model is registered; extend rather than replace.
11. **Workspace lists** — `GET /api/auth/workspaces/brands|agents/` for superuser picker.
12. **UsageRecord Decimal pattern** — `cost_amount` Decimal(10,4) is the correct money style (AI cost, not commissions).
13. **AgentProfile 1:1** — extend; do not create a second agent user table.
14. **Brand Agents nav slot** — `/brand/agents` and sidebar item already exist (placeholder copy).
15. **Agent dashboard shell** — `/dashboard` with `canAccessAgent` gate in `lib/paths.ts`.

---

## B. Existing functionality that partially implements the MISA business model

| Piece | What it does | Gap vs intended product |
|-------|----------------|-------------------------|
| `Product.commission` | Decimal % 0–100, validated in serializer | Not a $ amount; never calculated; no snapshot; no platform fee |
| `ProductShareLink` | One code per product; brand button increments `share_count`; public open increments `open_count` | No agent, team, campaign, or video FK; no event rows; OneToOne cannot be per-agent |
| Share POST | Brand-owner only (`IsBrandOwner`) | Agents cannot create links |
| Redirect | 302 to `product_url` | No conversion, no click vs open distinction, no session |
| `/brand/agents` | Nav + placeholder “marketplace coming next” | Wrong product copy (hire creators) vs team/invite/commission |
| `/dashboard` | Agent login landing | No browse, links, earnings, wallet |
| `AgentProfile` | bio | No payout account, no status, no public profile fields |
| `User.is_active` | Can deactivate a user in admin | No Brand suspend, no Agent suspend distinct from User |
| `SocialPost` | Saves `authorized=True` | Explicitly does not post: “Connect the social account to publish.” |
| `UsageRecord` | AI spend log | Not agent wallet / commission ledger |
| Superuser workspaces | Monitor brands/agents as lists | No finance, teams, links, withdrawals |
| Product share UI | Shows `share_count / open_count` | Brand metrics only; not agent performance |

**Commission field meaning today:** help_text is “Commission on sales, as a percentage.” The intended example ($1.00 gross, 3% platform fee, $0.97 net) is a **fixed currency amount + configurable platform %**. Do not silently treat `Product.commission` as dollars.

---

## C. Missing models

Recommended new app: **`commerce`** (tracking, commissions, wallets, withdrawals) so Studio/`ai` stays untouched. Team graph can live in **`brands`** + **`agents`**.

### Teams / membership (`brands` / `agents`)

- `Team` — brand-scoped agent team (1:1 with Brand is enough initially: “the brand’s team”).
- `TeamMembership` — agent User + team + status (`invited`, `pending`, `active`, `rejected`, `suspended`) + joined_at.
- `TeamInvitation` — brand → agent invite token, expiry, status.
- `JoinRequest` — agent → brand request, status, message.
- `Campaign` (optional Phase 2) — brand/product grouping for tracking; nullable FK on links.

### Status flags

- `Brand.status` (`active` / `suspended`) — today only User.is_active exists.
- `AgentProfile.status` (`active` / `suspended`).

### Tracking (`commerce`)

- `TrackingLink` — unique `code`; FKs: brand, product, agent, team, optional campaign, optional `VideoProject`; **not** OneToOne on Product.
- `TrackingEvent` — append-only: `link_created`, `link_opened`, `click`, `share_copied` (app-detectable only), `conversion`, `commission_generated`, `commission_reversed`. Store request meta (ip hash, ua, referer) without claiming social-platform share detection.
- Keep `ProductShareLink` as the **brand-level** share record. Do not overload it into affiliate links.

### Commission (`commerce`)

- `PlatformSettings` — singleton; `platform_fee_percent` Decimal (default 3.00, **not hard-coded in calculation code**).
- `CommissionRule` — scope: `global` | `brand` | `product` | `team` | `agent` (+ optional product/team/agent FKs); `rate_type` `percent` | `fixed`; `rate_value` Decimal; `priority`.
- `CommissionEntry` — **immutable snapshot** at conversion time: gross, fee_percent, fee_amount, agent_net, rule_id, product_id, link_id, event_id; Decimal fields; never recomputed from current Product.commission.

### Wallet / payout (`commerce`)

- `Wallet` — 1:1 agent (later brand wallet if needed); cached `available` / `pending` / `paid` Decimal, always reconcilable from ledger.
- `LedgerEntry` — append-only credit/debit; types: commission_credit, reversal, withdrawal_hold, withdrawal_paid, adjustment; Decimal amount; running balance optional but source of truth is the entry set.
- `PayoutAccount` — agent-configured destination (bank/e-wallet fields as text; no live PSP yet).
- `WithdrawalRequest` — amount Decimal, status `pending` / `approved` / `rejected` / `paid` / `cancelled`; FK wallet + payout account; admin review.

### Audit

- `AuditLog` — actor, impersonator, action, object, payload JSON. Django `LogEntry` is admin-only and insufficient for financial audit.

**Do not add:** a second User model, a second Product, a parallel Studio, or a float money field.

---

## D. Missing APIs

All new. Do not reuse `POST /api/brands/products/{id}/share/` as the agent link factory (it is brand-owner-only and OneToOne).

### Brand team

- `GET/POST /api/brands/teams/` (or `/api/brands/{id}/team/`)
- `GET /api/brands/team/members/`
- `POST /api/brands/team/invites/`
- `POST /api/brands/team/requests/{id}/accept|reject/`
- `PATCH /api/brands/team/members/{id}/` (suspend, special commission hook)
- `GET /api/brands/team/performance/` (after tracking exists)

### Agent catalog + membership

- `GET /api/agents/me/` PATCH (profile) — GET exists, PATCH does not
- `GET /api/agents/brands/` browse
- `GET /api/agents/products/` browse (approved membership only for full content)
- `GET /api/agents/content/` exported videos available to team
- `POST /api/agents/join-requests/`
- `GET /api/agents/invitations/` + `POST .../accept|reject/`

### Tracking

- `POST /api/agents/links/` create unique tracking link
- `GET /api/agents/links/` + stats
- `GET /s/<code>/` **dispatcher** — resolve TrackingLink first, else existing ProductShareLink
- Optional `POST /api/track/events/` for authenticated share_copied; conversion ingest (`POST /api/commerce/conversions/`) with a defined source (brand-reported / webhook). **Do not invent social share webhooks.**

### Commission / wallet

- `GET /api/commerce/settings/` (admin)
- CRUD commission rules (brand-scoped + admin global)
- `GET /api/agents/wallet/`
- `GET /api/agents/ledger/`
- `GET/POST /api/agents/payout-accounts/`
- `GET/POST /api/agents/withdrawals/`
- Admin: list/approve withdrawals, reverse commissions

### Permissions on existing AI routes

**Do not** grant `IsAgent` on `/api/ai/*`. Agents must not generate Studio videos in this plan.

---

## E. Missing frontend pages

| Audience | Missing page | Notes |
|----------|--------------|--------|
| Brand | Team members, invites, join-request inbox | Replace placeholder at `/brand/agents` |
| Brand | Special commission per member | After Phase 3 |
| Brand | Agent performance / campaign performance | After tracking |
| Agent | Browse brands / products / content | New under `/dashboard/...` or `/agent/...` |
| Agent | Invitations + join requests | |
| Agent | My tracking links + copy URL | |
| Agent | Link activity (opens/clicks) | Reliable events only |
| Agent | Earnings / commissions | |
| Agent | Wallet + withdraw | |
| Agent | Profile edit + payout account | Wire unused `agents.me` |
| Admin | Platform fee, withdrawals, finance, audit | Django admin first; optional `/admin` app later |
| Public | None required beyond `/s/:code` | Keep rewrite; do not build a fake “share detected” page |

Keep `/brand/studio` and all studio components as they are.

---

## F. Missing permissions

Today:

- `IsAgent` — role agent or superuser
- `IsBrandOwner` — role producer or superuser
- `IsSuperuser`
- Object scope: brand owner on products/projects; **no team membership check**

Need:

- `IsActiveBrand` / reject suspended brands
- `IsActiveAgent`
- `IsTeamMember` (active membership for that brand)
- `IsBrandTeamAdmin` (brand owner; later team managers)
- `IsPlatformAdmin` (reuse `IsSuperuser` initially)
- Object-level: agent may only create links for products they are approved to distribute
- Conversion/withdrawal: staff-only reverse/approve

Do **not** change `IsBrandOwner` on Studio endpoints.

---

## G. Missing tracking infrastructure

Current:

- One `ProductShareLink` per product
- `share_count` += 1 when **brand owner** clicks Share (link copy/create, not a social share)
- `open_count` += 1 on public GET `/s/<code>/`
- Redirect to `product.product_url` or 404 if empty
- Frontend: `products/page.tsx` only

Missing:

- Unique code per (agent × product × content × team × campaign)
- Event table (append-only)
- Distinction: link_created vs opened vs click (redirect is an **open**; a click is the same HTTP GET today — document as `link_opened` unless a landing page with a second CTA exists)
- Conversion ingest
- Content/video attribution (`VideoProject_id`)
- Honest share event: only “user copied link in MISA UI” — **not** TikTok/IG/FB share detection

**Redirect compatibility:** `ProductShareRedirectView` must keep serving existing brand codes. Add a lookup order: `TrackingLink.code` then `ProductShareLink.code`.

---

## H. Missing commission infrastructure

Current: `Product.commission` percentage stored on product; never applied.

Need:

1. **Configurable platform fee** on `PlatformSettings.platform_fee_percent` (seed 3.00).
2. **Rule precedence (highest wins):**
   1. Agent-specific override (agent + optional product)
   2. Team-specific rule
   3. Product rule (`Product.commission` or a `CommissionRule` with scope=product)
   4. Brand default
   5. Global/default rule
3. **Rate types:** `fixed` (e.g. $1.00) and `percent` of sale price. Snapshot **both** the chosen type and the computed gross at conversion.
4. **Math at conversion (Decimal):**
   - gross = resolved commission at that moment
   - fee = round(gross × platform_fee_percent / 100, 2)
   - agent_net = gross − fee  
   Example: gross $1.00, fee 3% → fee $0.03, net $0.97.
5. **Immutability:** `CommissionEntry` copies gross, fee_percent, fee_amount, net. Changing `Product.commission` later must not update old rows.
6. **Reversal:** new ledger + commission rows (`commission_reversed`); do not mutate the original entry.

`Product.commission` should remain as the **product-level default percent** for the catalog UI, with a later option to add a fixed-amount field or a rule row. Do not change the serializer’s 0–100 validation until a fixed-amount product field is added explicitly.

---

## I. Missing wallet / ledger infrastructure

Nothing exists. `UsageRecord.cost_amount` is AI vendor cost, unrelated.

Need:

- `Wallet` per agent
- `LedgerEntry` append-only Decimal
- Balance policy: `pending` (conversion not yet cleared) → `available` → `paid` (after withdrawal)
- Historical balances from ledger, not from current product settings
- No `float`

---

## J. Missing withdrawal / payout infrastructure

Nothing exists. Need payout account on agent, withdrawal request workflow, admin approve/reject/mark paid, ledger holds.

No payment-provider integration exists (`STRIPE` / bank API not in settings). Phase 4 can be **manual payout** (admin marks paid) without a PSP.

---

## K. Missing admin functionality

Django admin today: User, AgentProfile, Category, Brand, Product (+ inlines), ProductShareLink, all AI models.

Missing admin (register new models; add filters):

- Teams / memberships / invites / join requests
- Brand + agent suspend
- Platform fee
- Commission rules
- Tracking links + events
- Commission entries (read-only)
- Wallets / ledger (read-only)
- Withdrawal review
- Audit log
- Campaigns

Superuser acting-user is **not** a finance admin. Keep it for Studio support.

Optional later: a Next.js `/platform` admin. **Not required** to start; Django admin is enough for Phase 5 monitoring if models are well registered.

---

## L. Existing code that should NOT be duplicated

| Keep using | Do not copy into |
|------------|------------------|
| `accounts.User` + Token auth | New auth system |
| `TokenActingAuthentication` | Second impersonation stack |
| `IsAgent` / `IsBrandOwner` | Parallel permission files per app without reuse |
| `Brand` / `Product` / media | Second catalog |
| `ProductShareLink.generate_code` | New random helper (extract shared `allocate_code()`) |
| `/s/<code>/` rewrite + view | A second public redirect path unless codes collide by design |
| `VideoProject` media fields | Duplicate “content” table that copies files |
| `auth_payload` / `lib/api.ts` `api()` | New API client |
| Django admin | A full custom admin clone in Phase 1 |
| `UsageRecord` | Mixing AI cost into commission ledger |

---

## M. Existing code that should NOT be deleted

- Entire `ai` director workflow (`director_views.py`, `views.py` generate/QA/export)
- Legacy AI endpoints listed above (tests + possible scripts)
- `VoiceRecorder.tsx` and `POST /api/ai/transcribe/` (unused by Studio UI, still valid)
- `SocialPost` + publish authorization
- `ProductShareLink` + `ProductShareView` + products page share modal
- `StyleRecipe` APIs
- Superuser choose-account + acting headers
- Brand workspace layout / sidebar / studio components
- `accounts.tests`, `ai/tests/*`
- django-q cluster settings (tune workers later; do not remove)

---

## N. Migration risks

1. **`ProductShareLink.product` OneToOne** — cannot become per-agent without breaking existing rows and the products UI. **Add `TrackingLink`; do not alter uniqueness of ProductShareLink.**
2. **`Product.commission` meaning** — if changed from percent to money, existing product rows and frontend forms break. Keep field; add rules/fixed amount separately.
3. **SQLite ALTER** — adding FKs is fine; avoid multi-step table rebuilds in one migration without a fallback.
4. **Code uniqueness** — TrackingLink.code and ProductShareLink.code must not collide (shared allocator or namespaced codes).
5. **VideoProject.owner is User**, not Brand — content access for agents must go through `product.brand` + membership, not `owner==agent`.
6. **CASCADE deletes** — Product delete already cascades share link and video projects. New FKs should SET_NULL or PROTECT for financial rows (never CASCADE commission/ledger).
7. **Data migration for teams** — existing producers have brands but no Team; create Team 1:1 per Brand on migrate.
8. **AgentProfile backfill** — migration `agents/0002` already created profiles for role=agent; new status fields need defaults.
9. **Redirect behavior** — changing `/s/<code>/` without dual lookup 404s existing shared URLs.
10. **django-q ORM broker on SQLite** — extra write load from events; keep event inserts lightweight; do not enqueue a job per page open.

---

## O. SQLite limitations that matter for production

| Issue | Why it matters here |
|-------|---------------------|
| Single-writer | Tracking opens + commission + ledger under concurrent agents will serialize; lock timeouts |
| No robust row-level locking | Wallet check-then-withdraw needs `select_for_update`; weak on SQLite |
| ORM broker for django-q | Same DB as app; Studio generate already long-running; affiliate events must not compete with video jobs |
| Decimal is OK | SQLite stores Decimal as string via Django; still use DecimalField, not float |
| Concurrent F() counters | Current share/open F() updates work at low volume; event log is safer than hot counter rows at scale |
| Backup / ops | File DB is not suitable for money-in-production |

**Recommendation:** implement Decimal/ledger correctly on SQLite for development; **require PostgreSQL before real payouts**. Do not block Phase 1–3 on the database move, but do not market production wallets on SQLite.

---

## P. Recommended implementation order

1. Teams + invites + join requests + permissions (no money).  
2. Agent catalog of approved products/content + `TrackingLink` + event log + compatible `/s/<code>/`.  
3. Platform fee + commission rules + snapshot entries on conversion (conversion source: brand-reported or test ingest first).  
4. Wallet + ledger + payout account + withdrawal (manual admin payout).  
5. Brand/agent performance UIs + Django admin finance + audit log + tests/hardening.

Never open Studio generate to agents in these phases. Never replace ProductShareLink. Never hard-code 3%.

---

## IMPLEMENTATION PLAN

### Phase 1 — Teams, invitations, join requests, permissions

**Goal:** A brand can see a real team page; an agent can request to join or accept an invite. No wallets. No new share-link behavior.

**Backend — modify**

- `backend/brands/models.py` — `Team`, `TeamMembership`, `Brand.status`
- `backend/brands/admin.py`
- `backend/brands/serializers.py`
- `backend/brands/views.py`
- `backend/brands/urls.py`
- `backend/brands/migrations/0010_team_membership.py` (new)
- `backend/agents/models.py` — `AgentProfile.status` (+ optional display fields)
- `backend/agents/serializers.py`
- `backend/agents/views.py` — PATCH me; join-request + invitation endpoints
- `backend/agents/urls.py`
- `backend/agents/migrations/0003_agent_status.py` (new)
- `backend/accounts/permissions.py` — `IsActiveAgent`, `IsTeamMember`, `IsBrandTeamAdmin`
- `backend/accounts/admin.py` — list_filter already has `is_active`; keep
- `backend/config/urls.py` — only if a new include is added (prefer nested under existing apps)

**Backend — add tests**

- `backend/brands/tests/test_teams.py` (new; brands app has **zero** tests today)
- `backend/agents/tests/test_membership.py` (new)

**Frontend — modify**

- `frontend/app/brand/(workspace)/agents/page.tsx` — replace placeholder with team/invite/inbox UI
- `frontend/components/brand/BrandSidebar.tsx` — label “Agents” can stay; do not add Studio routes
- `frontend/lib/api.ts` — team/invite/join endpoints
- `frontend/app/dashboard/page.tsx` — links into new agent pages
- `frontend/lib/paths.ts` — only if new agent route helpers are needed

**Frontend — add**

- `frontend/app/dashboard/brands/page.tsx`
- `frontend/app/dashboard/invitations/page.tsx`
- `frontend/app/dashboard/profile/page.tsx`

**Do not touch:** `backend/ai/*`, studio page, ProductShareLink, `next.config.ts` rewrites.

---

### Phase 2 — Agent catalog, tracking links, reliable events

**Goal:** Approved members get unique links. Opens are logged. Brand share URLs keep working.

**Backend — new app `commerce` (recommended)**

- `backend/commerce/__init__.py`, `apps.py`, `models.py` (`TrackingLink`, `TrackingEvent`)
- `backend/commerce/admin.py`
- `backend/commerce/serializers.py`
- `backend/commerce/views.py`
- `backend/commerce/urls.py`
- `backend/commerce/services/codes.py` — shared allocator used by TrackingLink **and** ProductShareLink.generate_code
- `backend/commerce/services/tracking.py` — record_event()
- `backend/commerce/migrations/0001_initial.py`

**Backend — modify**

- `backend/config/settings.py` — `INSTALLED_APPS += "commerce"`
- `backend/config/urls.py` — `path("api/commerce/", include("commerce.urls"))`; keep `s/<code>/`
- `backend/brands/views.py` — `ProductShareRedirectView` dual lookup (TrackingLink then ProductShareLink); record `link_opened` when tracking
- `backend/brands/models.py` — `Campaign` if included here; optional FK from TrackingLink
- `backend/brands/models.py` — `ProductShareLink.generate_code` should call shared allocator (behavior unchanged)
- `backend/agents/views.py` + `urls.py` — create/list links; browse products/content (filter by active membership)
- `backend/ai/models.py` — **no schema change**; TrackingLink FK to VideoProject only

**Frontend — modify**

- `frontend/lib/api.ts`
- `frontend/next.config.ts` — only if a new public path is added (prefer keep `/s/:code`)
- `frontend/app/brand/(workspace)/products/page.tsx` — **do not remove** existing share modal
- `frontend/app/brand/(workspace)/videos/page.tsx` — optional “publish to team” later; not required if membership implies access to exported projects

**Frontend — add**

- `frontend/app/dashboard/products/page.tsx`
- `frontend/app/dashboard/content/page.tsx`
- `frontend/app/dashboard/links/page.tsx`

**Tests**

- `backend/commerce/tests/test_tracking.py`
- `backend/brands/tests/test_share_redirect.py` — existing ProductShareLink still 302s; new codes event-log

**Honesty rule:** UI copy must say “opens” / “link copied”, never “TikTok shares”.

---

### Phase 3 — Commission rules, platform fee, snapshot ledger rows

**Goal:** Configurable fee; precedence; conversion creates immutable `CommissionEntry` + ledger credit. Changing product commission later does not rewrite history.

**Backend — modify / add in `commerce`**

- `backend/commerce/models.py` — `PlatformSettings`, `CommissionRule`, `CommissionEntry`
- `backend/commerce/services/commissions.py` — resolve_rule(), calculate(gross, fee_percent) with Decimal, snapshot
- `backend/commerce/views.py` — rules CRUD; conversion ingest; admin settings
- `backend/commerce/admin.py`
- `backend/commerce/migrations/0002_commission.py`
- `backend/brands/serializers.py` — keep `validate_commission` 0–100; do not switch to dollars
- `backend/brands/models.py` — Product.commission remains percent default (document as product-level percent rule)

**Frontend — modify**

- `frontend/app/brand/(workspace)/products/page.tsx` — keep percent editor; add helper text that it is the product default %
- `frontend/app/brand/(workspace)/agents/page.tsx` — special rate override per member
- `frontend/lib/api.ts`

**Frontend — add**

- `frontend/app/dashboard/earnings/page.tsx`
- Optional brand `frontend/app/brand/(workspace)/commissions/page.tsx`

**Do not hard-code 3%.** Seed `PlatformSettings.platform_fee_percent = Decimal("3.00")`.

**Conversion source in this phase:** authenticated brand or admin POST (and tests). Do not pretend checkout exists.

---

### Phase 4 — Wallet, ledger, payout account, withdrawals

**Goal:** Agent sees pending/available/paid; can request withdrawal; admin marks paid. Manual payout (no PSP).

**Backend — `commerce`**

- Models: `Wallet`, `LedgerEntry`, `PayoutAccount`, `WithdrawalRequest`
- `backend/commerce/services/ledger.py` — post_entry(), balances from entries, hold on withdraw
- `backend/commerce/services/commissions.py` — on snapshot, credit pending/available per policy
- Views + urls for agent wallet/ledger/payout/withdraw
- Admin: withdrawal queue
- `select_for_update` on Wallet with a comment that PostgreSQL is required for production
- Migration `0003_wallet.py`
- Tests: `backend/commerce/tests/test_ledger.py`, `test_withdrawals.py` — Decimal only; reversal does not mutate old commission rows

**Frontend — add**

- `frontend/app/dashboard/wallet/page.tsx`
- `frontend/app/dashboard/payouts/page.tsx`

**Frontend — modify**

- `frontend/lib/api.ts`
- `frontend/app/dashboard/page.tsx` — summary stats once APIs exist

**Do not touch Studio or ProductShareLink.**

---

### Phase 5 — Admin monitoring, performance UIs, audit, hardening

**Goal:** Platform admin can monitor the affiliate graph; brands see agent performance; SQLite caveats documented; tests cover brands/agents/commerce.

**Backend — modify**

- `backend/commerce/admin.py` — list filters for links, events, commissions, wallets, withdrawals
- `backend/brands/admin.py` — team, campaign, brand status
- `backend/agents/admin.py` — status, payout account readonly
- `backend/accounts/admin.py` — unchanged except display if needed
- `backend/commerce/models.py` — `AuditLog` if not added earlier
- `backend/config/settings.py` — notes / env for future `DATABASES` Postgres; **do not switch DB in this phase unless explicitly requested**
- Performance aggregate endpoints: brand team stats, agent link stats (read models already written)

**Frontend — add / modify**

- `frontend/app/brand/(workspace)/performance/page.tsx` (or section on agents page)
- `frontend/components/brand/BrandSidebar.tsx` — one extra nav item at most
- `frontend/app/dashboard/page.tsx` — real dashboard, not stub
- Superuser: optional links from `/choose-account` to Django `/admin/` (already at backend `/admin/`)

**Tests**

- Expand `backend/accounts/tests.py` only if new permission classes need coverage
- Frontend vitest for API helpers if added in `frontend/lib/`

**Still out of scope unless separately requested**

- Real TikTok/IG/FB posting
- Agent access to Studio generate
- Payment-provider payouts
- Replacing SQLite in production without a dedicated migration project
- Deleting legacy `/api/ai/brief|script|generate` endpoints

---

## Call-graph files (quick index)

| Concern | Files |
|---------|--------|
| User / acting / permissions | `backend/accounts/models.py`, `authentication.py`, `permissions.py`, `views.py`, `urls.py` |
| Agent stub | `backend/agents/models.py`, `views.py`, `urls.py`, `serializers.py` |
| Brand / product / share | `backend/brands/models.py`, `views.py`, `urls.py`, `serializers.py` |
| Share redirect | `backend/config/urls.py`, `backend/brands/views.py` `ProductShareRedirectView` |
| Studio | `backend/ai/models.py`, `urls.py`, `views.py`, `director_views.py` |
| Admin | `backend/*/admin.py` |
| Frontend API | `frontend/lib/api.ts`, `auth.tsx`, `paths.ts` |
| Studio UI | `frontend/app/brand/(workspace)/studio/page.tsx`, `frontend/components/studio/*` |
| Share UI | `frontend/app/brand/(workspace)/products/page.tsx` |
| Agent UI | `frontend/app/dashboard/page.tsx`, `login/page.tsx`, `register/page.tsx` |
| Brand agents placeholder | `frontend/app/brand/(workspace)/agents/page.tsx` |
| Rewrites | `frontend/next.config.ts` |
| Queue / DB | `backend/config/settings.py` |

---

## Decision log (for implementers)

1. **Do not rebuild the application.** Extend `brands` + `agents` + new `commerce`.
2. **Do not replace AI Studio.** No `/api/ai/*` permission widening to agents.
3. **Do not delete** legacy analyze/brief/script/generate/transcribe or VoiceRecorder.
4. **Do not assume unused = deletable.** Call graph shows 11 `api.ts` keys unused by UI but covered by backend tests.
5. **Do not turn `ProductShareLink` into affiliate links.** OneToOne + brand-only POST is a different product feature.
6. **Do not use float for money.** DecimalField / Decimal only.
7. **Do not hard-code 3%.** `PlatformSettings`.
8. **Do not claim social share tracking** the platforms do not provide.
9. **Do not compute historical commission from live Product.commission.** Snapshot on `CommissionEntry`.
10. **SQLite is acceptable through Phase 3 development; PostgreSQL before real payouts.**
