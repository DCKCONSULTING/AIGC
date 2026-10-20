# MiSa Studio — System Situation Report

**Date:** 21 September 2026  
**Product:** MiSa (MISA) — AI product-video studio for brand owners  
**Backend project:** DckBrand  
**Scope:** Full current system — features, how it works, backend and frontend progress

This report describes the system **as it exists in code today**. It includes the studio upgrades shipped on 21 September 2026 (speed, languages, presenter identity, style-key bulk create).

---

## 1. Current situation

MiSa is a working full-stack product: brand owners log in, manage products, and generate **9:16 vertical commercial videos** through a director-led studio at `/brand/studio`.

The live path is:

1. Merchant fills a brief in ordinary business language (no prompt writing).
2. The system writes **3 creative concepts**.
3. The merchant picks a concept and edits a **5-scene storyboard** (duration-driven; default 45s ≈ 5 scenes).
4. **Gemini Omni** generates each scene as video **with native spoken audio**.
5. FFmpeg assembles the cut, burns captions, then QA runs.
6. The merchant reviews, amends, approves, and exports.

**What is production-ready (with API keys configured):** auth, brand/product CRUD, the six-step studio, parallel scene generation, presenter lock, languages, QA gates, export, style-key save/apply/bulk.

**What is not finished:** real social posting (authorize-only), Seedance as the default video engine, Kalodata unless keyed, agent-role studio access, and multi-worker queueing (django-q is set to 1 worker).

Local UI: `http://127.0.0.1:3000/brand/studio`  
API: Django REST at `/api/…` (token auth)

---

## 2. Architecture

```
Browser (Next.js 16, React 19, port 3000)
        │  REST + Token  (Authorization, optional X-Acting-User / X-Acting-Brand)
        ▼
Django 6.1 + DRF  (SQLite, django-q2, CORS)
        │
        ├── accounts   users, login, workspaces, superuser impersonation
        ├── agents     agent register / login / profile
        ├── brands     categories, brands, products, images, share links
        └── ai         studio director, generation, QA, style recipes
                │
                ├── Gemini Omni     scene video + spoken audio
                ├── Gemini Flash    concepts, copy, QA, analysis
                ├── Nano Banana     presenter identity stills (and legacy stills)
                └── FFmpeg          concat, captions, export
```

| Layer | Stack |
|-------|--------|
| Frontend | Next.js 16.3, React 19, TypeScript, Tailwind 4, Vitest |
| Backend | Django 6.1, DRF, django-q2, Pillow, google-genai |
| Database | SQLite (`backend/db.sqlite3`) |
| Media | `backend/media/` (products, scene clips, previews, finals, exports) |
| Video | Gemini Omni 1.1 Flash, 9:16, 720p, native audio |
| Jobs | django-q (1 worker), or a background thread if the queue is down |

Root API map:

| Prefix | App |
|--------|-----|
| `/api/auth/` | accounts |
| `/api/agents/` | agents |
| `/api/brands/` | brands |
| `/api/ai/` | studio / generation |
| `/s/<code>/` | product share redirect |
| `/admin/` | Django admin |

---

## 3. Who uses it

| Role | What they can do |
|------|------------------|
| **Producer** (brand owner) | Full studio: products, videos, generate, approve, export |
| **Agent** | Separate dashboard and profile. No studio generation path in the UI |
| **Superuser** | Can act as another user/brand via acting headers |

Public home (`/`) can collect a draft prompt and photos, then hand off into Studio after login.

---

## 4. Features (current)

### 4.1 Accounts and workspaces

- Brand register / login (username or email)
- Agent register / login
- Token authentication
- Preferences: default language, speaking style, speaker gender
- Superuser workspace picker (`/choose-account`)

### 4.2 Brands and products

- Categories, brands, products
- Product facts used as **product truth** in video: name, price, variants, materials, dimensions, offer, approved/prohibited claims
- Product photos (required before generate) and optional demo videos
- Share links with open/share counts

### 4.3 Studio director (main product)

Six UI steps:

| Step | Screen | Purpose |
|------|--------|---------|
| 1 | Brief | Product + story + speaker + presenter + style key |
| 2 | Concepts | Generate and pick 1 of 3 directions (or mix scenes) |
| 3 | Storyboard | Edit VO, captions, locks, order, duration |
| 4 | Generate | Queue Omni; poll live status |
| 5 | Review | Preview, QA cards, corrections, amendments |
| 6 | Approve | Approve, export 9:16, optional social authorization |

Supporting studio features:

- Duration 30 / 45 / 60 seconds (default 45 → typically **5 scenes**)
- Tone: Friendly, Casual, Energetic, Premium
- Gender: Female, Male, Neutral
- Must-remain locks: product, logo, packaging, presenter, price, etc.
- Optional reference video or style images (style only — cannot override product facts)
- Draft save / resume from previous versions
- Per-scene regenerate, duplicate, reorder, approve

### 4.4 Speaking languages

Nine locales, all marked ready in the UI:

| ID | Spoken language |
|----|-----------------|
| `conversational_bm` | Conversational Bahasa Malaysia |
| `formal_bm` | Formal Bahasa Malaysia |
| `bm_english` | BM + English mix |
| `english` | English |
| `chinese` | Mandarin Chinese |
| `cantonese` | Cantonese |
| `hokkien` | Hokkien |
| `mandarin_my` | Malaysian Mandarin |
| `tamil_my` | Malaysian Tamil |

The presenter is instructed to **speak that language out loud** in Omni’s native audio. Captions follow the same language.

### 4.5 Presenter identity

Presenters are **not** HeyGen-style avatars. Identity is:

1. A **reference photograph** used in every scene job, and
2. A **locked prompt** (same face, hair, clothing).

Options:

- **Upload yourself:** front / left / right / looking up / looking down
- **Described look:** European, Chinese, Malaysian Chinese, Malay, Indian, African, Middle Eastern, Japanese, Korean, Southeast Asian, Latino, Mixed, or custom text
- **Generated identity still** if no photo is uploaded (Nano Banana portrait, then reused)

Look and language are independent (example: Malaysian Chinese presenter speaking Malay or English).

Prompt-only (no photo) is weaker; the recommended path is photo + lock.

### 4.6 Style key and bulk create

After a video the merchant likes:

1. Save it as a **style key** (name such as “Air fryer kitchen UGC”).
2. Reuse that key on other products — same scene quality, camera, lighting, presenter recipe.
3. **Bulk create** up to **10** videos: pick products, optionally change presenter, tone, or background (for example a different kitchen).

The 5-scene structure is copied; product facts and voice-over are filled for each new product.

### 4.7 QA, approve, export

- Structural checks: product, price, claims, captions, narration, audio, CTA, scene completeness, presenter lock
- Visual QA: frames compared to original product photos (and presenter photo when present)
- Release-blocking issues stop approval until fixed or (for some visual warnings) explicitly confirmed
- Export is a 9:16 file via FFmpeg
- Social (TikTok / Instagram / Facebook) stores **authorization only** — nothing is posted yet

---

## 5. How it works (end to end)

### 5.1 Brief → concepts → storyboard

1. Merchant selects a product (must already have photos and a price).
2. Brief answers: viewer action, customer, main benefit, optional offer, locks, background, presenter.
3. Backend saves `VideoProject.creative_brief` (`schema_version: 2`).
4. `DirectorService.generate_concepts()` asks Gemini for **three different** 9:16 concepts with full scene timelines.
5. Merchant picks one (or mixes scenes). Backend writes `Scene` rows: hook, product in use, product detail, presenter, lifestyle / CTA as they fit the duration.
6. Merchant can edit VO, captions, camera, locks, and duration. Copy review rewrites spoken lines into the selected language.

Scene count is duration-driven (`duration // 8`, clamped 4–8). **45 seconds → 5 scenes.** That structure was not changed for speed work.

### 5.2 Generate (backend pipeline)

`POST /api/ai/video/{id}/generate/` enqueues `VideoGenerationService.run`:

| Phase | Status | What happens |
|-------|--------|----------------|
| Snapshot | — | Freeze product facts so generation cannot invent prices/claims |
| Analyze | `analyzing` | Product analysis; optional reference video; Kalodata if keyed |
| Plan | `planning` | Use the merchant’s storyboard (studio skips rewriting the script from scratch) |
| Video | `generating_video` | **Start all scene Omni jobs together**, then poll until each finishes |
| Voice | `generating_voice` | Studio **keeps Omni audio** (no separate Google TTS) |
| Assemble | `assembling` | FFmpeg concatenates clips and burns captions |
| QA | `qa_running` | Structural + visual checks; amendment suggestions |
| Ready | `ready_for_review` | Preview URL available |

**Speed (21 Sep 2026):** scenes no longer wait in a queue of five sequential 2-minute jobs. All five `start()` first; the wall clock is roughly **one scene’s generation time**, not five stacked. Poll interval default is **2 seconds** (`GEMINI_OMNI_POLL_SECONDS`).

Each Omni call gets:

- First frame: **original product photo** (required)
- Extra references: presenter identity photo(s), then optional style images (max 4 images total)
- Compiled prompt: PRODUCT TRUTH + CREATIVE DIRECTION + LOCKED ATTRIBUTES + SAFETY

Studio does **not** fall back to a silent still if a scene fails. A failed scene fails the run.

### 5.3 Review → approve → export

- Frontend polls `/api/ai/video/{id}/status/` every 2.5s while generating.
- Review shows preview, QA layer cards, and amendment assistant.
- Merchant can correct in natural language or regenerate one scene.
- Approve is blocked by missing/failed required checks (silent audio, product visual mismatch, invented claims, incomplete CTA).
- Export writes `export-9x16.mp4`.

### 5.4 Style key apply / bulk

Saving a style stores a JSON blueprint: language, tone, gender, presenter, location, lighting, and per-scene camera/pace/role **without** product-specific claims.

Applying or bulking:

1. Creates (or updates) a draft project for each product.
2. Rebuilds the same scene skeleton with that product’s name, price, and benefit.
3. Copies presenter photos from the source project when present.
4. Queues generation.

---

## 6. Backend progress

### 6.1 Status

| Area | Status |
|------|--------|
| Auth, brands, products | Done |
| Director brief / concepts / timeline | Done |
| Parallel Omni scene generation | Done (21 Sep) |
| Native scene audio (no extra TTS in studio) | Done |
| Languages including EN / Chinese / Cantonese / Hokkien | Done (21 Sep) |
| Presenter photos + ethnicity + identity still | Done (21 Sep) |
| StyleRecipe save / apply / bulk (max 10) | Done (21 Sep) |
| QA + approval gates | Done |
| FFmpeg assemble + export | Done |
| Social **posting** | Not implemented (authorize record only) |
| Seedance as default engine | Not wired (class exists) |
| Kalodata insights | Optional; empty without keys |

Latest AI migration: **`0006_style_recipe_and_languages`** (StyleRecipe table + new language choices). Applied.

### 6.2 Core models (`ai`)

- `VideoProject` — brief, script, scenes, status, preview/final/export, QA
- `Scene` — order, VO, caption, duration, clip, metadata (locks, prompts, QA)
- `VideoAsset` — images/video/audio; presenter refs and style refs in metadata
- `StyleRecipe` — named style key owned by the merchant
- `MerchantPreference` — default language / style / gender
- `UsageRecord`, `SocialPost`, `VideoProjectVersion`

### 6.3 Main AI APIs

**Director**

- `POST /api/ai/video/creative-brief/`
- `POST /api/ai/video/concepts/` and `/video/{id}/concepts/`
- `POST /api/ai/video/{id}/select-concept/`
- `GET/PATCH /api/ai/video/{id}/timeline/`
- `POST /api/ai/video/{id}/generate/`
- Scene patch / delete / duplicate / regenerate
- `POST /api/ai/video/{id}/correct/` · `/amendments/` · `/qa/` · `/approve/` · `/export/`

**Style keys**

- `GET/POST /api/ai/styles/`
- `GET/DELETE /api/ai/styles/{id}/`
- `POST /api/ai/styles/{id}/apply/`
- `POST /api/ai/styles/{id}/bulk/`
- `POST /api/ai/video/{id}/save-style/`

**Also:** preferences, product/reference analyze, legacy one-shot `POST /api/ai/video/generate/`, usage list.

### 6.4 Key backend files

| File | Role |
|------|------|
| `ai/models.py` | Projects, scenes, style recipes, languages |
| `ai/urls.py` | All `/api/ai/` routes |
| `ai/director_views.py` | Brief, concepts, timeline, styles, generate |
| `ai/views.py` | List/detail, status, approve, export, presenter uploads |
| `ai/services/video.py` | Generation pipeline, parallel Omni |
| `ai/services/director.py` | Concepts, storyboard, copy review |
| `ai/services/compiler.py` | Scene prompts + locks |
| `ai/services/presenter.py` | Identity text, photos, stamping |
| `ai/services/style_recipes.py` | Save / apply / bulk |
| `ai/providers/google/omni.py` | Gemini Omni start / poll / save |
| `ai/tests/test_studio_speed_style.py` | Parallel start, languages, presenter, style API |

### 6.5 Tests

Covered: studio API, director workflow, audio pipeline, visual QA, Gemini helpers, and the 21 Sep suite (`test_studio_speed_style`: languages present, presenter in prompt, all scene jobs `start` before `poll`, style key bulk rebuilds blueprint).

---

## 7. Frontend progress

### 7.1 Status

| Area | Status |
|------|--------|
| Public site (home, about, login, register) | Done |
| Brand workspace shell | Done |
| Products / brands / videos / profile pages | Done |
| Studio 6-step wizard | Done |
| Speaker locale including new languages | Done (21 Sep) |
| Presenter controls (look + multi-angle upload) | Done (21 Sep) |
| Style key dropdown, apply, bulk create, save-on-review | Done (21 Sep) |
| Generation progress + QA review + approve/export | Done |
| Logged-in studio browser pass for this report | Blocked (login required; no credentials used) |
| Agent studio | Not built |

### 7.2 Routes

| Route | Purpose |
|-------|---------|
| `/` | Public home + draft seed |
| `/brand/login` · `/brand/register` | Producer auth |
| `/brand/studio` | Main director studio |
| `/brand/videos` | Library |
| `/brand/products` · `/brand/brands` | Catalog |
| `/brand/profile` · `/brand/dashboard` | Account |
| `/login` · `/register` · `/dashboard` | Agent |
| `/choose-account` | Superuser acting |

### 7.3 Studio UI (21 Sep additions on Brief)

- **Speaker:** tone, gender, locale (9 languages)
- **Presenter:** look dropdown, custom description, photo slots (front/left/right/up/down), short note that identity is locked with a reference photo
- **Background / location** on the brief
- **Style key:** pick a saved key, apply to this product, bulk-create similar videos, save current look from Review

### 7.4 Key frontend files

| File | Role |
|------|------|
| `frontend/app/brand/(workspace)/studio/page.tsx` | Studio orchestration |
| `frontend/lib/api.ts` | Endpoints and types (including `StyleRecipe`) |
| `frontend/lib/studio.ts` | Steps, languages, presenter options, QA helpers |
| `frontend/lib/director.ts` | Brief form, presenter payload |
| `frontend/components/studio/PresenterControls.tsx` | Presenter UI |
| `frontend/components/studio/StyleKeyPanel.tsx` | Style key + bulk |
| `frontend/components/studio/CreativeBriefWizard.tsx` | Brief + location |
| Other studio components | Concepts, timeline, progress, review, approve |

Frontend unit tests (`vitest`): studio steps, languages include english/chinese/cantonese/hokkien, director brief helpers.

---

## 8. Configuration that must be present

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Omni video + concepts + QA |
| `GEMINI_OMNI_MODEL` | Default `gemini-omni-1.1-flash` |
| `GEMINI_OMNI_POLL_SECONDS` | Default `2` |
| `NANO_BANANA_MODEL` | Presenter identity stills |
| `FFMPEG_PATH` | Optional; otherwise PATH / imageio-ffmpeg |
| `AI_SYNC_TASKS` | `true` runs jobs inline (useful for debugging) |
| `KALODATA_API_KEY` | Optional market insights |
| `NEXT_PUBLIC_API_URL` | Frontend → backend base URL |

Without a Google key, studio cannot start video jobs.

---

## 9. Known limits

1. **One worker.** django-q `workers = 1`. Bulk of 10 videos queues them; they generate one project at a time unless more workers are added.
2. **Studio has no silent-still fallback.** A bad Omni scene fails the whole video.
3. **Omni clip length** is 3–10 seconds per scene.
4. **Product photo + price** are mandatory.
5. **Social publish** is a saved intent, not a live post.
6. **SQLite** is the current database; parallel **HTTP** generation is used so scene jobs do not fight the DB.
7. **Agent accounts** cannot run Studio in the current UI.
8. **Identity still generation** adds a short extra step when the merchant does not upload a face; uploads skip that step.

---

## 10. What to verify next (product)

1. Time a real 45s / 5-scene generate on `/brand/studio` (expect closer to one Omni wait, not ~10 minutes stacked).
2. Generate the same brief in English, Chinese, Cantonese, and Hokkien; confirm spoken audio matches.
3. Upload four face angles and confirm the same person across all five scenes.
4. Save a style key from a kitchen UGC, bulk two other products with a different presenter or kitchen.
5. Confirm QA still blocks approve when audio is missing or the product is redesigned.

---

## 11. Summary

The system is a **director-led 9:16 product-video studio** with a complete merchant path from brief to export. Backend and frontend both include the 21 September work: **faster parallel scenes**, **four extra speaking languages**, **consistent presenter via photo lock**, **self-as-presenter uploads**, **open presenter look selection**, and **style-key bulk create**. Remaining gaps are operational (queue workers, live social post, optional Kalodata) rather than missing studio steps.

*Report generated from the codebase on 21 September 2026.*
