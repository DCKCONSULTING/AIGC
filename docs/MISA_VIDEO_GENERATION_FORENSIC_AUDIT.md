# MISA Video Generation Forensic Audit

Analysis only. No code, configuration, or dependency was changed.

Evidence is the current tree under `backend/ai` and `frontend`, the installed SDK `google-genai==2.21.0`, the live SQLite database `backend/db.sqlite3`, and the process list on this host (gunicorn for HTTP, `manage.py qcluster` for jobs). Timing numbers below come from `creative_brief.generation_metrics` written by `backend/ai/services/generation_metrics.py`. They are wall-clock measurements already stored on real projects. They are not guesses. Where a split (Google vs poll vs FFmpeg) is not stored, that gap is stated.

There is no Celery app and no Redis broker in this repository. The queue is django-q2 with the Django ORM (`backend/config/settings.py` `Q_CLUSTER`, lines 201–212).

---

## Executive Summary

A Studio “Generate” click does not wait on Google. `ProjectGenerateView.post` (`backend/ai/director_views.py` 372–418) sets the project to `queued` and calls `enqueue_video_generation`. The browser then polls `GET /api/ai/video/<id>/status/` every 2.5 seconds (`frontend/app/brand/(workspace)/studio/page.tsx` 296–347).

The worker runs `VideoGenerationService.run` (`backend/ai/services/video.py` 94–147). For a Studio project the expensive step is `_create_videos`. Each scene is one blocking `client.interactions.create` to model `gemini-omni-1.1-flash` at `720p`, `background=false`, `store=true`, timeout 600 seconds (`backend/ai/providers/google/omni.py` 103–123). Up to `VIDEO_SCENE_CONCURRENCY` (configured **6**) of those calls run together in a `ThreadPoolExecutor` (`video.py` 591, 724–735).

Stored continuity on recent projects is off. Every recent scene row has `requires_previous_scene_continuity = 0`. `_stamp_continuity` writes that flag as `False` unless the storyboard already asked for the previous frame (`director.py` 1228–1235). `previous_frame_required` is never written anywhere else in the backend. So a normal 6-scene video submits all 6 Omni calls in one wave.

Measured successful 45-second Studio videos at concurrency 6 (projects 187, 188, 189, 175, 176, 177, 196, 197, 198, 201):

| | seconds |
|---|---:|
| Fastest `total_generation_seconds` | 121 (project 198) |
| Median of those 10 | about 194 (3.2 min) |
| Slowest of those 10 | 275 (project 188, 4.6 min) |

The same rows show the Omni wave, not the script, is the critical path. Script/storyboard are usually under 1 second once the storyboard already exists. Assembly (FFmpeg crossfade to 1080×1920) is 25–56 seconds on those jobs.

A 10–15 minute wait is real, and it is a different mode. Projects 210 and 213 stayed at progress 64 (“Creating scenes together”) for about 15 and 18 minutes and were then cancelled, with no scene timing rows. Progress is written before the blocking `interactions.create` calls and is not updated again until a scene in that wave finishes (`video.py` 575–579, then the thread pool blocks). The client timeout on each create is 600 seconds, and a retryable failure starts another create, up to 3 attempts (`video.py` 750–754).

Veo is configured (`VEO_MODEL=veo-3.1-generate-preview`) and `VeoProvider` exists, but no service calls it. Image generation (`gemini-2.5-flash-image`) is skipped on the Studio path. QA is skipped on the Studio path. Character and product photos are re-encoded into every Omni request; they are not regenerated per scene.

Under 5 minutes is already the common case for one Studio video when Omni returns. It is not a guarantee. The tail is the blocking Omni create, multiplied by bulk jobs sharing 6 django-q workers and by retries.

---

## 1. Current Architecture

```
Browser  studio/page.tsx  onGenerateProject
   |  POST /api/ai/video/<id>/generate/     (returns 202 immediately)
   v
gunicorn (3 workers, timeout 300s)  ProjectGenerateView
   |  status=queued, enqueue_video_generation
   v
django-q2  ORM queue on SQLite   manage.py qcluster   workers=6  timeout=7200
   |  ai.tasks.generate_video_project
   v
VideoGenerationService.run
   |  snapshot + preflight
   |  _analyze / _plan          (usually no new LLM if brief+script+scenes exist)
   |  _create_videos
   |     ThreadPoolExecutor(max_workers=6)
   |        GeminiOmniProvider.start  -->  google.genai Client.interactions.create
   |           model gemini-omni-1.1-flash, 720p, 9:16, duration 3–10s, native audio
   |        then sequential: files.get until ACTIVE, files.download, FFmpeg prepare
   |  _create_voice             (no-op for Studio)
   |  _assemble                 FFmpeg xfade + scale to 1080x1920
   |  QA                        skipped when is_studio_project
   v
SQLite  VideoProject.preview_video + creative_brief.generation_metrics
   ^
Browser polls status every 2500ms until status leaves the active set
```

Dependency map with the functions that implement each arrow:

| Arrow | File | Function | Lines |
|---|---|---|---|
| Generate button | `frontend/app/brand/(workspace)/studio/page.tsx` | `onGenerateProject` | 913–940 |
| API | `frontend/lib/api.ts` | `endpoints.ai.videoProjectGenerate` | 118 |
| HTTP | `backend/ai/urls.py` | `video/<pk>/generate/` | 85 |
| Endpoint | `backend/ai/director_views.py` | `ProjectGenerateView.post` | 372–418 |
| Queue | `backend/ai/tasks.py` | `enqueue_video_generation` → `_enqueue` | 25–26, 81–93 |
| Worker body | `backend/ai/tasks.py` | `generate_video_project` | 11–13 |
| Orchestrator | `backend/ai/services/video.py` | `VideoGenerationService.run` | 94–147 |
| Scene wave | `backend/ai/services/video.py` | `_create_videos` / inner `begin` | 514–735 |
| Google call | `backend/ai/providers/google/omni.py` | `GeminiOmniProvider.start` | 68–170 |
| File poll | `backend/ai/providers/google/omni.py` | `check` / `poll` | 180–247 |
| Download | `backend/ai/providers/google/omni.py` | `save_video` / `_download_uri` | 249–299 |
| Per-scene encode | `backend/ai/services/video.py` | `_prepare_generated_clip` | 1247–1277 |
| FFmpeg | `backend/ai/services/ffmpeg.py` | `prepare_scene_clip`, `assemble_project` | 436–499, 669–703 |
| Status poll | `backend/ai/views.py` | `VideoStatusView.get` | 402–406 |
| UI poll | `frontend/app/brand/(workspace)/studio/page.tsx` | `setInterval` 2500ms | 296–347 |

Studio bulk uses a second entry point that still lands in the same worker function: `onBulkGenerate` → `POST /api/ai/video/<id>/bulk-generate/` → `bulk_generate_from_studio` → one `enqueue_video_generation` per child (`studio_bulk.py` 297–298).

The separate Bulk Studio product (`/api/ai/bulk-video/<id>/generate/`) uses `BulkVideoGenerationService.start_generation` → `advance` → `enqueue_bulk_item` → `run_item` → the same `VideoGenerationService.run` (`bulk_studio.py` 624–778).

---

## 2. Single Video Generation Flow

### A. Frontend

Component: `frontend/app/brand/(workspace)/studio/page.tsx`.

The storyboard button calls `onGenerate` (`StoryboardTimeline.tsx` line 187), which is `onGenerateProject` (page line 1494).

`onGenerateProject` (913–940):

1. Requires a selected concept and scenes (`canVisitStudioStep("generate")`).
2. `saveBrief()` first.
3. `beginGenerationTimer(saved.id)` — UI clock only (`GenerationTimer.tsx` ticks every 1s).
4. `POST /api/ai/video/<id>/generate/` with the auth token and no extra body.
5. Response is the serialized project already in `queued` (HTTP 202). The browser does not hold the HTTP connection for generation.
6. `keepProject` + `go("generate")`.
7. The effect at lines 296–347 polls status every **2500ms** while `ACTIVE_STATUSES` contains the status. On a terminal status it fetches the full project. There is no websocket and no SSE.

### B. Backend

`ProjectGenerateView.post` (`director_views.py` 375–418):

- Rejects if status is already in `_STALE_STATUSES` (already generating).
- `require_intelligence()` and `require_omni_key()`.
- Requires `selected_concept_id` and at least one scene.
- Refreshes product snapshot and character snapshot, runs `preflight_project`.
- Writes `status=queued`, `stage_label="Preparing director plan"`, `progress=4`.
- `enqueue_video_generation(project.pk)`.
- Returns 202.

`_enqueue` (`tasks.py` 81–93): if `AI_SYNC_TASKS` is false (it is, `.env` `AI_SYNC_TASKS=false`), it calls `django_q.tasks.async_task("ai.tasks.generate_video_project", project_id)`. If that import/call throws, it falls back to a daemon `threading.Thread`. With `qcluster` running, the normal path is the ORM queue.

Database row: the existing `VideoProject` is updated. Scenes already exist from concept selection. No new scene rows are created on this click when a storyboard is present (`video.py` 120–122).

### C. Preparation inside `run`

Order in `VideoGenerationService.run` (94–147), each wrapped by `timed_phase` except voice:

| Phase key | What it does on a Studio project that already has a storyboard | Model calls | Measured |
|---|---|---|---|
| `project_creation` | `_refresh_snapshot`, `refresh_unfrozen_character_snapshot`, `preflight_project` | none | 13–140 ms |
| `script_generation` | `_analyze` then `_plan` | usually none | usually 20–100 ms; see below |
| `storyboard_generation` | scenes already exist, so `_sync_scenes` is skipped; images skipped | none | 2–12 ms |
| `scene_generation` | `_create_videos` | one Omni call per scene that needs a clip | 87–241 s wall on the sample |
| voice | `_create_voice` returns immediately for Studio (`video.py` 1280–1285) | none | not timed |
| `assembly` | `_assemble` | none | 25–56 s on the 45s sample |
| `qa` | not entered when `is_studio_project` (`video.py` 134) | none on Studio | absent on recent Studio rows |

`is_studio_project` is true when `selected_concept_id` is set or `creative_brief.schema_version == 2` (`director.py` 140–144). Every recent generated project has `schema: 2` and a concept id.

`_analyze` (`video.py` 245–282) calls product analysis, Kalodata, and reference analysis only when those JSON fields are empty. Failures are logged and skipped.

`_plan` (`video.py` 357–392): if a concept and scenes exist, it does not rebuild the brief or script. Studio calls `DirectorService._align_captions_to_speech`, which is a local string rewrite, not a model call (`director.py` 607–637). Non-studio calls `review_copy`, which is one `IntelligenceClient.generate_json` to `GEMINI_MODEL` (`director.py` 513–536). That call sits inside the `script_generation` timer. Project 117 recorded `script_generation_ms = 234887` (235 s). Project 201 recorded 10586 ms. Most later jobs are under 100 ms because the script was already stored and `_plan` returned after the local caption align (`video.py` 358–379).

Image generation is gated by:

```python
if self.omni.family() != "1.x" and not is_studio_project(project):
    self._create_images(project)
```

`GeminiOmniProvider.family` always returns `"omni"` (`omni.py` 62–63). The `"1.x"` branch is dead. Studio therefore never calls `_create_images`. A legacy non-studio project would generate one Nano Banana still per scene, sequentially (`video.py` 462–495).

`_ensure_presenter_identity` (`video.py` 1204–1245) runs inside `_create_videos` before any Omni call. If a Master Character reference exists, it stamps that file and returns. It calls Nano Banana only when Studio wants a presenter and no image is on disk.

### D. Per-scene work

For each scene that is not locked, not approved, and has no usable clip (`video.py` 537–572):

1. Prompt: `compile_scene_prompt` (`compiler.py` 79). Local string build. No model.
2. Product image: `_product_first_frame` (`video.py` 1430–1441), passed as `image_path` to every scene.
3. Character / product / style refs: `refs_for` → `_reference_images` (`video.py` 609–621, 1465–1535). Up to 4 paths. Master character path is included once, not regenerated.
4. Previous-scene last frame: only if `requires_previous_scene_continuity` is true. On stored projects it is false, so this branch does not run.
5. Google: `GeminiOmniProvider.start` (`omni.py` 68–170).
6. There is no separate “operation create” then long-running poll of the interaction. `background=False` makes `interactions.create` block until the video payload or URI comes back, timeout 600 s (`omni.py` 105–122). The comment at 105–107 says a later `interactions.get` fails with “Multiple authentication credentials received”, so status is not polled on the interaction id.
7. After create returns a `file_id`, the worker calls `files.get` until state `ACTIVE` (`omni.py` 180–220, loop in `video.py` 791–802).
8. Download: `client.files.download` (`omni.py` 276–279).
9. Processing: `inspect_audio`, then `_prepare_generated_clip` → `prepare_scene_clip` (scale to 1080×1920, burn caption, libx264 `veryfast` CRF 23).
10. QA: not per scene on Studio.
11. Persistence: `scene.video_clip`, metadata `status=generated`, `record_scene_timing`, `VideoAsset`.

Scene timing recorded today is one number: `wall_started` at the beginning of `begin()` through the end of download + FFmpeg (`video.py` 629, 977–986). It does not split submit, Google, poll, download, and encode.

### Measured timeline, project 201 (45 s, 6 scenes, concurrency 6, continuity off)

From `generation_metrics` on project 201. Status `ready_for_review`. Model on every scene: `gemini-omni-1.1-flash`.

| Stage | ms | seconds |
|---|---:|---:|
| project_creation | 13 | 0.013 |
| script_generation | 10586 | 10.6 |
| storyboard_generation | 7 | 0.007 |
| scene wave wall (`scene_generation_parallel_ms`) | 125980 | 126.0 |
| scene-1 recorded duration | 91334 | 91.3 |
| scene-2 | 99020 | 99.0 |
| scene-3 | 106060 | 106.1 |
| scene-4 | 112746 | 112.7 |
| scene-5 | 119168 | 119.2 |
| scene-6 | 125943 | 125.9 |
| assembly | 33401 | 33.4 |
| qa | not recorded | — |
| total_generation | 179028 | 179.0 |

The six scene durations rise by about 6–8 seconds in storyboard order, and the parallel window equals the last scene. That pattern repeats on projects 175, 187, 188, 189, 196. It matches the code: all `start()` calls in the wave run together, then `pending_batch` is walked in scene order and each clip is downloaded and re-encoded before the next scene’s `completed_at` is written (`video.py` 746–1058). The first scene’s duration is the best available proxy for “Omni create + that scene’s encode”. Later scenes add the encode queue.

Project 201 proxy:

- Omni-dominated portion (scene-1): about 91 s
- Sequential tail across 6 encodes (scene-6 minus scene-1): about 35 s
- Assembly after the wave: 33 s
- Preparation: 11 s
- Total: 179 s

No row stores poll count or download bytes, so those are not given a measured duration.

---

## 3. Multi-Scene Generation Flow

Scene count is fixed by duration (`backend/ai/services/durations.py` 7–13, 31–33):

| Requested video | Scenes | Each scene (equal split) | Omni clamp |
|---|---:|---:|---|
| 15 s | 3 | 5.0 s | 3–10 s (`omni.py` 65–66) |
| 30 s | 5 | 6.0 s | same |
| 45 s | 6 | 7.5 s | same |
| 60 s | 6 | 10.0 s | same |

Older rows (projects 138–147) still have 8 scenes and `scene_concurrency: 3`. Current `SCENE_COUNTS` no longer emits 8 scenes. Those rows are historical.

### Actual graph for a current Studio video

`_stamp_continuity` (`director.py` 1228–1235) sets `requires_previous_scene_continuity` to false unless that key or `previous_frame_required` was already on the scene. Nothing in the backend sets `previous_frame_required`. The last 15 completed/failed projects in SQLite have the flag `0` on every scene.

`needs_continuity` (`video.py` 602–603) therefore returns false. `predecessor_ready` (`video.py` 696–705) returns true immediately. `launch_ready` takes the first `concurrency` ready jobs and submits them together (`video.py` 707–735).

```
Scene 1 ──┐
Scene 2 ──┤
Scene 3 ──┼── ThreadPoolExecutor, max 6 ── sequential download+FFmpeg ── xfade assembly
Scene 4 ──┤
Scene 5 ──┤
Scene 6 ──┘
```

Shared inputs, not ordering edges:

- shared product photo (`image_path=product_frame` on every `start`)
- shared master character file inside `image_paths` (up to 4, deduped)
- shared style text inside the compiled prompt (`continuity_state` in the brief)
- no shared previous video, no shared previous frame, when the flag is false

### If the flag is true

`predecessor_ready` waits until the previous scene id is in `done_ids`. `done_ids` is updated only after the clip is saved (`video.py` 976) or the scene is failed (`video.py` 773). A chain of 8 continuity scenes would be:

```
Scene 1 → Scene 2 → Scene 3 → … → Scene 8
```

Scene 1 has no predecessor, so it starts. Each later scene waits for the previous clip, then may run beside other scenes whose predecessors are done, up to the concurrency cap. A single chain has only one ready scene at a time, so concurrency does not overlap that chain.

`test_continuity_scenes_start_in_parallel` (`test_video_optimization.py` 119–148) only asserts that all four `start` calls eventually happen and that the stored concurrency value is 3. It does not assert overlapping start times.

### “If there are 8 scenes, can all 8 be submitted to Google at the same time?”

No, for two independent reasons in the current code:

1. `VIDEO_SCENE_CONCURRENCY` is clamped to 8 in settings (`settings.py` 197) but the live value is **6**. `launch_ready` only submits `concurrency - len(pending_batch)` jobs (`video.py` 717–718). A seventh and eighth scene wait until a slot frees, and a slot frees only after that scene’s blocking `start()` returns and the batch’s post-processing loop moves on. With 6 workers in the pool, at most 6 `interactions.create` calls are in flight for one video.
2. If `requires_previous_scene_continuity` is true, a scene is not submitted until the previous scene is in `done_ids`.

With the flag false, which is what production rows show, 6 of 6 current scenes are submitted together. Eight historical scenes were submitted 3 at a time (`scene_concurrency: 3` on projects 138–147).

Maximum safe concurrency for independent scenes is the configured cap of 6 per video, further limited by one Gemini API key and by how many videos the qcluster is already running (see section 20). Continuity chains must stay sequential.

---

## 4. Bulk Generation Flow

There are two bulk implementations. They are not the same.

### Path A — Studio “Generate N videos” (the concepts screen)

Frontend: `onBulkGenerate` (`studio/page.tsx` 688–736).

`POST /api/ai/video/<sourceId>/bulk-generate/` → `ProjectBulkGenerateView` (`director_views.py` 340–369) → `bulk_generate_from_studio` (`studio_bulk.py` 227–301).

For each expanded job it clones a `VideoProject`, binds the character, `select_concept` (copies that concept’s scenes locally), preflight, sets `queued`, then after the loop:

```python
for project_id in queued_ids:
    enqueue_video_generation(project_id)
```

(`studio_bulk.py` 297–298)

This path does **not** call `bulk_concurrency()` and does **not** create `BulkGeneration` rows. Every child is a normal django-q task. django-q runs `Q_CLUSTER["workers"]` of them at once. That value is 6 (`settings.py` 201–204, `.env` `Q_CLUSTER_WORKERS=6`). A request for 10 videos therefore runs 6 immediately and leaves 4 in the ORM queue until a worker finishes.

`MAX_BULK` is 10 (`style_recipes.py` line 19).

Each of those 6 workers then opens its own scene pool of 6. Worst in-flight Omni calls from Studio bulk: 6 videos × 6 scenes = 36, all on one `GEMINI_API_KEY`.

Evidence that this overlap slows Omni: projects 196, 197, and 198 were created in the same second (`2026-10-06 09:39:46`) and each ran 6 scenes at concurrency 6. Their parallel windows were 191 s, 155 s, and 87 s. Same model, same scene count, different wait.

### Path B — Bulk Studio (`/brand/.../studio/bulk`, `/api/ai/bulk-video/`)

`BulkVideoGenerationService.start_generation` (`bulk_studio.py` 624–659) marks items queued, then `advance` (694–725):

- `select_for_update` on the batch row
- running slots = items in `GENERATING`
- `slots = bulk_concurrency() - running`
- `bulk_concurrency()` is `BULK_VIDEO_CONCURRENCY`, live value **5**, hard cap 8 (`bulk_studio.py` 219–220, `settings.py` 198)
- only that many items are set to `GENERATING` and `enqueue_bulk_item`
- `run_item` calls `VideoGenerationService().run` and then `advance` again (`bulk_studio.py` 727–776)

So path B is a hybrid: up to 5 videos at once, each with up to 6 scene threads, and the next video starts when one `run()` returns. It is not “video 1 fully done, then video 2” and it is not “all 10 at once”.

```
video 1 ──┐
video 2 ──┤
video 3 ──┼── at most 5 (path B) or 6 (path A) videos
video 4 ──┤     each video: up to 6 Omni calls together
video 5 ──┘
video 6..10 wait on the django-q ORM queue (path A) or on advance() (path B)
```

Frontend for path B polls `bulk-video/<id>/status` on an interval in `frontend/app/brand/(workspace)/studio/bulk/page.tsx` (timer at line 116). Path A polls each child project’s video status every 2.5 s (`studio/page.tsx` 350–372).

---

## 5. Single vs Bulk Comparison

| Stage | Single video | Studio bulk (path A) | Bulk Studio (path B) | Sequential? | Parallel? | Bottleneck? |
|---|---|---|---|---|---|---|
| Brief | Already saved before Generate. `_plan` does not rebuild it if scenes exist. | Cloned from source (`studio_bulk.py` 167–206). No new brief model call. | One plan-time Gemini JSON call when the plan is generated, before Generate. | Plan is one call. | No | No, on the Generate click |
| Script | Local caption align. Copy review only if not Studio. | `select_concept` copies the concept script. | Built into the variation plan. | Yes, per project | Projects overlap | Rarely. Project 117 was 235 s. |
| Storyboard | Skipped when scenes exist (`video.py` 121–122). | `select_concept` writes scenes in the request, before the queue. | Scenes copied in `_prepare_item_project`. | Yes, in the HTTP request for path A | No across scenes | Seconds, in the POST, not in Omni |
| Character | Load master file once per project (`_ensure_presenter_identity`). | Each child binds its own character id. Same file reused if the character is shared. | Same. | Load is local | — | Encode-per-scene, not a new image |
| Images | Skipped for Studio. | Skipped for Studio clones. | Skipped once the child is a Studio project (`schema_version` 2). | n/a | n/a | No on Studio |
| Scene 1–6 | One wave, concurrency 6, continuity off. | Same, inside each video. | Same. | Post-process yes. Omni calls no. | Up to 6 starts | Yes. Omni create. |
| Video generation | `interactions.create`, blocking, 600 s cap | Same, multiplied by running videos | Same, cap 5 videos | The create itself is one HTTP wait | Thread pool | Yes |
| Polling | `files.get` after create, sleep 5 s only while not ACTIVE | Same per video | Same | Per video, the check loop is serial | — | Small if the file is already ACTIVE |
| Download | Serial after the wave | Serial inside each video | Same | Yes | No | Secondary (folded into the scene staircase) |
| QA | Skipped | Skipped | Skipped | — | — | No |
| Assembly | One xfade encode, 25–56 s measured | One per video, after that video’s scenes | Same | Yes, after scenes | No | Second largest measured stage |
| DB updates | Status, metrics JSON, each scene row | Same per child | Plus batch item rows and `select_for_update` | Writes are serial on SQLite | — | Not the multi-minute wait |

Difference that matters: bulk does not make one video faster. It runs several full `VideoGenerationService.run` calls at once and they share one Gemini key, 6 qcluster workers, and one SQLite file.

---

## 6. Google Models Found in Repository

| Model id | Found in code / env | Actually called on the Generate path | API | Purpose |
|---|---|---|---|---|
| `gemini-omni-1.1-flash` | `.env` `GEMINI_OMNI_MODEL`, default in `settings.py` 176, `omni.py` 59 | Yes. Every stored scene row says this model. | `client.interactions.create` | Scene video + native audio |
| `gemini-3.6-flash` | `.env` `GEMINI_MODEL` (overrides the code default) | Yes, but not for video pixels. `GeminiProvider.generate_content` via `IntelligenceClient` | `models.generate_content` | Concepts, copy review, QA text, transcription |
| `gemini-2.5-flash` | Code default only (`settings.py` 175). Overridden by env. | Not while `.env` is loaded | same | Unused default |
| `gemini-2.5-flash-image` | `.env` `NANO_BANANA_MODEL`, `nano_banana.py` 49–50 | Not during Studio scene generation. Used for master-character creation and optional presenter still / poster / legacy scene stills. | `models.generate_content` with `IMAGE` modality | Still images |
| `veo-3.1-generate-preview` | `.env` `VEO_MODEL`, `veo.py` 36–37 | No call site outside `VeoProvider`, and nothing constructs `VeoProvider` in services | `models.generate_videos` long-running operation, poll every 8 s (`veo.py` 53–66) | Dead code path |
| `veo-3.1-fast-generate-preview` | Not in repo | No | — | — |
| `veo-3.1-lite-generate-preview` | Not in repo | No | — | — |
| `gpt-4.1` | default `OPENAI_MODEL` | Only if Gemini intelligence fails and `OPENAI_API_KEY` is set (`intelligence.py` 105–111) | Chat completions | Fallback text |
| `dreamina-seedance-2-0-260128` | `SEEDANCE_MODEL` | `providers/seedance.py` exists. `VideoGenerationService` accepts a `seedance` argument and assigns it to `self.omni` (`video.py` 89). Production code passes nothing, so the object is `GeminiOmniProvider`. | BytePlus HTTP | Not on the current path |
| `openclaw/default` | `CLAW_MODEL` | Intelligence fallback only | OpenAI-compatible | Not video |

Installed SDK: `google-genai` **2.21.0** (venv). Requirements pin `google-genai>=1.40` (`backend/requirements.txt` line 6). Also installed for speech: `google-cloud-speech`, `google-cloud-texttospeech`. `google-cloud-aiplatform` is not installed. No `google-generativeai` (the older package).

---

## 7. Google Models Currently Used

Production video pixels: **`gemini-omni-1.1-flash` only.**

Confirmed by:

- `GeminiOmniProvider.start` sends `model=self.model` (`omni.py` 108–109).
- `self.model` reads `GEMINI_OMNI_MODEL` (`omni.py` 59).
- `.env` sets `GEMINI_OMNI_MODEL=gemini-omni-1.1-flash` and `GEMINI_OMNI_RESOLUTION=720p`.
- Every completed scene metric in the sample has `"model": "gemini-omni-1.1-flash"`.

Text around the video (concepts, and non-studio copy review / QA): **`gemini-3.6-flash`** via `settings.GEMINI_MODEL`.

Still images off the critical path: **`gemini-2.5-flash-image`**.

Speech synthesis (`SpeechProvider`) runs only when the project is not Studio and Google speech credentials exist (`video.py` 1279–1306). Studio voice is the audio track inside the Omni file. `generate_audio` is accepted by `start` and immediately discarded (`omni.py` 77–83): “Omni always produces native audio”.

---

## 8. Google Models Available / Potential Alternatives

Compared with Google’s Gemini API docs as retrieved for this audit (ai.google.dev, Omni guide and Veo 3.1 guide). “Available to this project” means the installed SDK can call the endpoint and the env already has a Gemini API key. It does not mean the key is allowlisted for every preview model. That was not probed with a live generate call.

| Model | SDK can call it? | Used now? | Fits current inputs? | Latency note from Google, not from this DB |
|---|---|---|---|---|
| `gemini-omni-1.1-flash` | Yes. `interactions.create` is what `google-genai` 2.21 exposes and what the code calls. | Yes | Text + up to 4 images + optional video. 3–10 s. 9:16. Native audio. Resolutions documented: 360p, 720p, 1080p (1080p described as upscaled). | Current measured scene proxy about 56–180 s at 720p. |
| `gemini-omni-flash-preview` | Same API shape, different model string. | No | Same family. Docs list it as the preview id. | Not measured here. |
| Omni at `360p` | Same call. Change `response_format.resolution`. | Resolution is `720p`. | Same inputs. Docs: 360p is a supported resolution. Google’s Omni 1.1 post says 360p generation is up to 60% faster than 720p on their throughput numbers. That is their claim, not a MISA measurement. | Would still be upscaled to 1080×1920 by FFmpeg (`ffmpeg.py` 40–42, 436–445). Quality drop is real. |
| `veo-3.1-generate-preview` | Yes, `VeoProvider` already calls `generate_videos`. | Configured, never invoked. | Text, one image, optional video. Durations in this provider are clamped to 4–8 s (`veo.py` 41), not 3–10. Reference images in Google’s Veo guide are a different config (`reference_images`, up to 3) that `VeoProvider` does not send. Native audio. Long-running operation polled every 8 s. | Not measured. Replacing Omni would drop multi-image reference-to-video and 10 s clips unless `VeoProvider` is rewritten. |
| `veo-3.1-fast-generate-preview` | The same `generate_videos` method accepts a model string. Not wired. | No | Google’s model page lists it beside `veo-3.1-generate-preview`. Fast is the speed variant; Google forum notes it is weaker on fine detail. | Not measured. Would not be faster inside the current Omni function; it is a different API. |
| `veo-3.1-lite-generate-preview` | Same, if the key can access it. | No | Docs: no 4K, no extension. Input text/image. | Not measured. |
| `gemini-2.5-flash-image` | Already used for stills. | Master character / posters / legacy stills | Cannot replace a scene video. | Irrelevant to the Omni wait. |
| `gemini-3.6-flash` | Already used for JSON. | Concepts and QA text | Not a video generator. | — |

Google’s own video overview says to use Gemini Omni Flash as the default video model, and Veo 3.1 when you need extension or last-frame control. MISA’s continuity design (optional previous-frame image) matches Omni `reference_to_video` more than Veo’s last-frame API. Switching the live path to Veo Fast would be a new provider call, not a one-line model rename, and it would not keep the current 4-image reference payload (`omni.py` 301–306 chooses `reference_to_video` when more than one image is attached).

Nothing in the installed SDK invents a faster Omni model than `gemini-omni-1.1-flash`. The speed levers Google documents on this same model are resolution (`360p`) and `background=false, store=false, stream=false`. The code already sets `background=false` and `stream=false`. It sets `store=true` (`omni.py` 111). Google’s best-practices note says `store=false` is the faster unary setting and then you cannot use `previous_interaction_id`. MISA does not send `previous_interaction_id` today.

---

## 9. Exact API / SDK Flow

Client construction (`backend/ai/providers/google/client.py` 51–58):

- `from google import genai`
- If `GEMINI_API_KEY` is set, `GOOGLE_API_KEY` is removed from the process environment so the SDK does not send both.
- `genai.Client(api_key=GEMINI_API_KEY)`
- Not Vertex. `vertexai=True` is never passed. `google-cloud-aiplatform` is not installed.

Video request body built in `GeminiOmniProvider.start`:

- `model`: `gemini-omni-1.1-flash`
- `input`: up to 4 inline base64 images (`data` + `mime_type`), optional video, then the text prompt
- images larger than 4 MiB are skipped with a warning (`omni.py` 318–320)
- `background`: `False`
- `store`: `True`
- `stream`: `False`
- `generation_config.video_config.task`: `reference_to_video` if more than one image or image+video; `image_to_video` if exactly one image; else `text_to_video` (`omni.py` 301–306)
- `response_format`: `type=video`, `delivery=uri`, `aspect_ratio=9:16`, `duration="{n}s"`, `resolution=720p`
- `timeout`: 600
- `number_of_videos`: not sent (one video per interaction)
- seed: not sent
- audio flag: deleted, always native
- first/last frame: not a Veo frame field. The product photo is an input image. A previous-scene JPEG is another input image only when continuity is on.

Return handling: interaction id, `output_video.uri` → `files/{id}`, optional inline bytes. If both URI and inline exist, inline is discarded (`omni.py` 134–140). Missing URI and missing bytes raise `MISSING_VIDEO_OUTPUT`.

Then `files.get(name=files/...)` until `ACTIVE`, then `files.download`.

---

## 10. Polling Analysis

Two different waits are easy to mix up.

### Wait 1 — inside `interactions.create` (the long one)

`background=False` means the HTTP call blocks until Google returns the video URI or errors, up to 600 s (`omni.py` 108–122). This is not a sleep loop in MISA. There is no poll interval here. Scene durations of 56–180 s on successful jobs are this wait plus the later serial encode of that scene.

While this call is in flight, `_create_videos` does not write a new progress row. The UI stays on the message set just before the pool starts: “Creating N scenes together” at progress 64 (`video.py` 575–579). Projects 210 and 213 were cancelled from that state after roughly 15 and 18 minutes.

### Wait 2 — `files.get` after the URI exists

`check` (`omni.py` 180–220) is one GET. The worker loop (`video.py` 791–918) calls it for each job in `pending_batch` in order. If the state is not `completed` / `ACTIVE`, the job stays pending. After the pass, if anything is still pending, the worker sleeps `poll_interval()` (`video.py` 1059–1072).

`poll_interval` (`omni.py` 173–178): `GEMINI_OMNI_POLL_SECONDS`, default **5**, clamped to 1–8. The variable is not set in `.env`, so the live interval is 5 seconds. `GeminiOmniProvider.poll` uses the same interval (`omni.py` 222–247) but the live loop prefers `check` when it exists (`video.py` 796–801), so the full `poll()` sleep loop is the fallback.

Google’s own URI example sleeps 5 seconds between `files.get` calls (Omni guide, “Retrieving videos with an URI”). MISA matches that.

Overhead that is only the sleep, after the file is already ACTIVE:

- If the first `files.get` returns `ACTIVE`, sleep is 0. Cost is one HTTP round trip, then download.
- If the file becomes ACTIVE just after a check, the next check waits up to one interval: **5 seconds worst, about 2.5 seconds average**.
- That 5 seconds is not the 90–180 second scene time.

Worst case if the file never becomes ACTIVE: the scene loop also enforces 600 s from `job["started_at"]` (`video.py` 833, 861, 891) and then fails the scene. `started_at` is set when `create` returns (`video.py` 667), so this second 600 s is on top of the create timeout. A single scene can therefore occupy the worker for about 600 s (create) + 600 s (file never ACTIVE) before failure, and a retryable error schedules another attempt.

Retries sleep `min(2 ** (attempt - 1), 8)` seconds before requeue (`video.py` 776–777): 1 s then 2 s. That backoff is negligible next to another full create.

Frontend polling (2.5 s) adds at most one interval after the worker writes `ready_for_review`. It does not add minutes. The stale sweeper in `VideoStatusView` marks a job failed if `updated_at` is older than 20 minutes and the status is still active (`views.py` 390–398). During the blocking create, `updated_at` is not refreshed, so a create that runs past 20 minutes can be marked failed by the next status GET while the worker is still blocked.

---

## 11. Image Generation Analysis

Studio Generate does not generate a still per scene.

`_create_images` (`video.py` 462–495) loops scenes one by one and calls `NanoBananaProvider.generate_image` (`nano_banana.py` 25–56, model `gemini-2.5-flash-image`). The call is skipped for Studio, as shown in section 2.

What does happen on the video request:

- Product photo bytes are read and base64-encoded inside `_media_part` for every scene (`omni.py` 308–328). Same file, repeated CPU and a larger JSON body each time. Not a second image-model call.
- Master character bytes are encoded the same way, once per scene, from the stored approved file.
- If the presenter is missing entirely, `_ensure_presenter_identity` makes one Nano Banana call (`video.py` 1231–1233) before the wave. That is once per project, not once per scene.
- Legacy non-studio path: 1 image call per scene plus 1 thumbnail (`video.py` 497–512), all sequential, all before video, and failures are swallowed (`logger.warning`, generation continues).

Image generation is not the multi-minute Studio bottleneck. The duplicate work is re-encoding the same JPEGs into every Omni body.

---

## 12. Character Reference Analysis

Master image lifecycle:

- Created earlier by `MasterCharacterService.generate` (`master_character.py` 121+) with one Nano Banana call from the front photo. That is a user action on the character, not part of Generate.
- Stored on `CharacterMasterReference`. Video preflight refuses to start without an approved master unless `generate_character` is set (`test_master_character.py` describes this gate; `preflight_project` is called from `ProjectGenerateView` 408).
- At generation, `materialize_character_references` + `uses_master_reference` (`video.py` 1204–1214). If the master file exists, it is stamped and returned. It is not sent back through Nano Banana.
- `_reference_images` puts at most one master path into the Omni input list, position 2 after the product photo (`video.py` 1495–1508), shared by every scene.
- Each `start()` reads that file from disk again and base64-encodes it again (`omni.py` 327).

No per-scene regeneration of the face. The extra cost is repeated read + base64 + upload inside each blocking create. A file over 4 MiB is dropped and the scene proceeds without it (`omni.py` 318–320), which is a quality bug more than a latency bug.

---

## 13. Product Reference Analysis

- Source: first existing path in `product_snapshot`, else the first product image (`video.py` 1430–1441).
- Required. Missing photo raises `ProviderError("Add a product photo before generating.")` before any Omni call (`video.py` 533–535).
- Passed as `image_path` on every scene (`video.py` 648–650).
- Also included in `image_paths` via `_reference_images` (`product_paths[:1]`). `_media_part` dedupes by resolved path (`omni.py` 314–316), so the same file is not attached twice in one request.
- No resize step before upload. No cache of the base64. No per-scene product image generation on Studio.
- Legacy `_create_images` would call Nano Banana with those photos as references, sequentially, once per scene. Studio does not.

---

## 14. Video Configuration Analysis

Exact arguments on every scene request (`video.py` 648–656 and `omni.py` 85–122):

| Parameter | Value | Latency effect |
|---|---|---|
| model | `gemini-omni-1.1-flash` | The wait |
| resolution | `720p` | Google documents 360p as faster and 1080p as an upscale. MISA then scales to 1080×1920 anyway. |
| aspect_ratio | `9:16` only; anything else is forced to 9:16 (`omni.py` 86) | Fixed |
| duration | scene length clamped to 3–10 s. 45 s video → six 7.5 s clips. 60 s → six 10 s clips. | Longer clips are a longer model job. Not separately instrumented. |
| number of videos | 1 per call, implicit | — |
| audio | always on | Cannot be disabled in this provider |
| reference images | product + master (+ previous frame only if continuity) , max 4 | Switches task to `reference_to_video` when count > 1 (`omni.py` 302–303). Extra upload bytes on the blocking POST. |
| first frame | product photo as an image part, not a Veo `image` start frame | Same upload |
| last frame | not sent | — |
| seed | none | — |
| extension / previous_interaction_id | none | Each scene is a fresh generation |
| background / store / stream | false / true / false | Google says `store=false` is the faster unary mode |

1080p or 4K is not what Omni is asked for. The 1080×1920 file the user downloads is an FFmpeg scale of a 720p Omni clip (`TARGET_WIDTH/HEIGHT` in `ffmpeg.py` 40–42). Raising Omni to 1080p would add Google’s upscale step and a heavier download, then FFmpeg would encode 1080 again. Lowering Omni to 360p is the only resolution change aimed at latency, and it makes the mandatory 1080 upscale softer. That tradeoff is quality, not a free win.

Shorter scene duration (15 s video = 3 scenes of 5 s) reduces how much video Google must paint and reduces FFmpeg work. It does not remove the per-call overhead. Best measured 15 s jobs in the older concurrency-3 era (projects 135, 136) had parallel windows of 62 s and 67 s and totals around 90–96 s, with assembly under 2 s. Those numbers are from concurrency 3 and an older build; they still show short videos finish faster.

---

## 15. Post-Processing Analysis

After Google returns bytes or a URI, for each scene, in order, on the worker thread (not a pool):

1. `save_video` downloads to a temp `.mp4` (`video.py` 920–924, `omni.py` 249–279). One download. Not downloaded twice unless `DOWNLOAD_FAILED` retries (up to 3, `video.py` 1027–1052).
2. `inspect_audio` runs ffprobe (`ffmpeg.py` `inspect_audio` / `probe_media`).
3. `_prepare_generated_clip` almost always re-encodes. The skip requires no caption and `clip_is_assembly_ready` (exactly 1080×1920, 30 fps, audio present) (`video.py` 1258–1270, `ffmpeg.py` 393–408). Omni output is 720p at 24 fps per Google’s model table, so the skip does not hit. Encode is libx264 `veryfast`, CRF 23, full threads (`ffmpeg.py` 62–74).
4. The encoded bytes are written through Django storage onto the scene (`video.py` 932–936). Local filesystem, not a second cloud bucket.
5. `_extract_final_frame` runs ffprobe + a frame grab (`video.py` 973, 1443–1463) even when continuity is off. The frame is stored only in the in-memory `last_frame_paths` dict. With continuity false it is never read. That is duplicate FFmpeg work on every successful scene.
6. Temp download file is deleted (`video.py` 1055–1057).

Then `_assemble` (`video.py` 1310–1411):

- If `clip_prepared` is true for every clip, captions are not burned again (`ffmpeg.py` 682–684).
- `concat_clips` tries a 0.28 s xfade (`SCENE_TRANSITION_SECONDS`, `ffmpeg.py` 46, 510–516, 547–584). That is another full x264 encode of the joined video. On failure it falls back to concat copy, then to a re-encode.
- `export_vertical` copies if the file is already 1080×1920/30 fps, otherwise scales again (`ffmpeg.py` 638–666).
- Preview is saved by reading the whole output back into memory (`video.py` 1362).
- `save_video_poster` grabs a poster. Failures are logged.

Measured assembly on recent 45 s successes: 24.9 s, 27.4 s, 33.4 s, 33.5 s, 36.0 s, 39.4 s, 44.9 s, 46.8 s, 50.1 s, 55.8 s (projects 198, 196, 201, 188, 187, 176, 197, 177, 175, 189).

60 s historical jobs 152 and 153 recorded assembly of 96–98 s. Those totals are not comparable one-for-one with current 6-scene jobs, but they show the crossfade grows with clip length and count.

No moviepy. No OpenCV. FFmpeg is a subprocess (`ffmpeg.py` 49–56), binary from `FFMPEG_PATH`, `PATH`, or `imageio-ffmpeg`.

Data movement: Google → temp file → encode temp → Django file field → (assembly reads those files) → another encode → preview field. The bytes are not uploaded to Google a second time. They are encoded twice (per-scene, then xfade).

---

## 16. QA Analysis

Studio `run()` does not call `_quality` (`video.py` 134–144). Recent Studio metrics have no `qa_ms` except older rows (129 and neighbors) whose `qa_started_ms` is hours earlier than `project_creation_started_ms`, so that 109 s figure was left behind in the JSON from an earlier run. It is not the current Studio critical path.

Non-studio `QAService.run` (`qa.py` 144–198):

- Local truth checks.
- One Gemini JSON review of the script (`generate_json`, model `GEMINI_MODEL`).
- `VisualQAService.analyze_project` walks scenes **one by one** (`visual_qa.py` 133–146). Cache hit skips a scene. A miss samples frames with FFmpeg and calls Gemini with the images (`visual_qa.py` around 394).
- Identity gates (`identity_qa.py`) sample frames and audio again.
- Failures in the Gemini QA call become a warning check, not an automatic regenerate (`qa.py` 168–182).
- Studio delivery does not wait on this.

Manual “re-check” is `POST /api/ai/video/<id>/qa/` from `rerunQa` (`studio/page.tsx` 1005–1017), after the video is already reviewable.

QA does not regenerate scenes by itself. Regeneration is a separate user action (`SceneRegenerateView`, amendments).

---

## 17. Retry / Failure Analysis

### Inside one scene

`begin` increments `attempt` (`video.py` 627).

- Missing API key, or `retryable` false, or `attempt >= 3`: `_finish_failed_scene`. No more creates.
- Otherwise delay 1 s then 2 s and another full `interactions.create` (`video.py` 749–789).

Three attempts means up to three full Omni generations for that scene. Successful siblings are not deleted.

Download failures retry the download only, up to 3, without a new create (`video.py` 1027–1052).

Silent audio on Studio is a retryable `ProviderError` (`video.py` 926–930), so a silent clip can burn another full create.

### What a failed scene does to the rest

Studio: the failure is recorded, the scene is added to `done_ids`, other scenes in the wave keep running, and after the loop the first failure is raised (`video.py` 1081–1091). `run()` then `mark_failed` unless a preview already exists (`video.py` 159–166).

Clips that already saved stay on disk with `status=generated`. The next `run()` skips a scene when the clip exists, `needs_regeneration` is false, it is not a fallback, and status is not `failed` / `qa_failed` (`video.py` 542–550).

So: one failed scene does **not** regenerate the successful scenes on the next attempt. It also does **not** stop the other scenes in the current wave. The project as a whole is marked failed, so the user sees a failed video and uses “Retry generation”, which calls full `onGenerateProject` → `run()` again, and the skip rule keeps the good clips.

`mark_continuity_stale` (`director.py` 1766–1778) sets `needs_regeneration` on later scenes that have `requires_previous_scene_continuity`. With the flag false, that list is empty (`continuity_dependents`, `director.py` 1749–1763). A failure does not invalidate later scenes in current data.

Non-studio fallback: if Omni fails and it is not a silent-audio error, `_finish_failed_scene` builds a still-image clip with FFmpeg and marks `qa_failed` (`video.py` 1116–1161). Studio does not do that. Studio leaves the scene failed and fails the project.

Scene-level retry from the UI: `SceneRegenerateView` (`director_views.py` 274–337) sets `needs_regeneration` on that scene plus continuity dependents, then `enqueue_scene_regeneration`. `regenerate_scenes` (`video.py` 284–337) renders only those scenes (`force=True` on that subset) and reassembles. Locked scenes are skipped.

Worst case wasted Omni time: 3 attempts × 600 s create timeout on one scene, while the other five scenes in the wave still run and are kept. The user waits for the slowest attempt chain. There is no measured 3-attempt success in the recent metric sample (`retry_count` 0 on the completed scenes inspected).

---

## 18. Celery / Redis / Worker Analysis

Celery is not used by MISA. Celery processes on this machine belong to other projects (`webgen`, `dckfood`, `commeta_app`).

MISA queue:

- Library: `django-q2` (`requirements.txt` line 9).
- Broker: database ORM, not Redis (`settings.py` 210 `"orm": "default"`).
- Workers: `Q_CLUSTER_WORKERS` default 6, clamped 1–8. Live env is 6.
- `timeout` 7200 s, `retry` 7260 s, `max_attempts` 2 (`settings.py` 205–207). A task that exceeds 7200 s can be requeued. Combined with in-function retries, a stuck job can run twice at the django-q layer.
- `sync` follows `AI_SYNC_TASKS`, which is false.
- Host process: `manage.py qcluster` is running (parent pid 3085946 at the time of this audit, plus cluster children).

One qcluster worker runs one `generate_video_project` (or one `generate_bulk_item`) to completion. Inside it, up to 6 threads block on Omni. The worker does not pull another video until `run()` returns. Prefetch is django-q’s default ORM polling; there is no Celery `worker_prefetch_multiplier` in this repo.

`ack_failure` / result backend: not customized beyond the cluster dict. Tasks are plain functions, not chains, chords, or groups. Bulk fan-out is a Python loop of `async_task`, or `advance()` releasing the next ids.

HTTP tier: gunicorn, 3 workers, `--timeout 300`, unix socket. Generate returns 202 before Omni, so the 300 s gunicorn timeout does not cover video generation. It would cover a slow `bulk_generate_from_studio` POST if concept cloning for 10 videos ever exceeded 300 s. That POST is local DB work plus `select_concept`, not Omni.

---

## 19. Database Analysis

Engine: SQLite at `backend/db.sqlite3` (`settings.py` 96–103), `timeout` 20 seconds.

Writes on the hot path:

- `mark_progress` several times per project (status, progress, stage_label).
- `timed_phase` saves the whole `creative_brief` JSON at phase start and end (`generation_metrics.py` 35–50).
- `record_scene_timing` saves that JSON again after every scene (`generation_metrics.py` 108).
- Each scene row is saved when marked generating, when the Omni id is stored, and when the clip is stored (`video.py` 551–554, 687–690, 1537–1546, 962–972).
- `provider_request_id` on the project is overwritten by each scene as its create returns (`video.py` 687–689). Last writer wins. Not a lock across videos.
- Path B bulk takes `select_for_update` on the batch (`bulk_studio.py` 696). Path A does not.

SQLite serializes writers. Six workers saving large `creative_brief` blobs can stall each other for short periods. The measured phase times for snapshot and storyboard are tens of milliseconds, so this is not the 2–4 minute Omni wait. It can add jitter while six videos finish scenes at once.

Status polling is a single-row read every 2.5 s per active project. Cheap next to Omni.

There is no generation-metrics table. Timestamps live inside `creative_brief`, and a later short run overwrites phase keys while old scene rows can remain (project 200: `total_generation_seconds` 31.6 with scene durations of 53–88 s and `assembly_started` a few milliseconds after storyboard). Treat `total_generation_seconds` as “the last `run()` that reached `mark_total`”, and scene rows as the last timing stored for that scene id. They are not always one consistent timeline.

---

## 20. Frontend Perceived Latency

Perceived wait = queue time until a qcluster worker starts + `run()` + up to 2.5 s until the next status poll.

The POST itself returns as soon as the task is queued. The UI timer starts at `beginGenerationTimer` before the POST (`studio/page.tsx` 928–929), so it includes a bit of save-brief and request time.

`created_at` → `updated_at` is not generation time. Project 200 was created at 11:05 and last updated at 11:53, while the last `run()` recorded 31.6 s. The clock the user feels during Generate is the status poll plus the UI timer.

Progress 64 with the label “Creating N scenes together” means the worker is inside the blocking Omni wave. That label does not move until a scene finishes post-processing (`video.py` 1059–1065). A 3-minute Omni wave looks frozen. A 15-minute hung create looks identical.

No websocket. Missing one poll costs 2.5 s, not minutes.

---

## 21. Critical Path

For a current Studio video with an existing storyboard and continuity off:

| Step | Role |
|---|---|
| Save brief + POST + ORM enqueue | Non-critical. Sub-second to a few seconds unless the queue is backed up. |
| Snapshot, preflight, caption align | Non-critical. Measured 0.01–11 s. |
| Product / character file read | Non-critical, but on the thread that then blocks. |
| `interactions.create` for the slowest scene in the wave | **Critical path.** |
| Serial FFmpeg of the other scenes after the first returns | **Critical path.** Adds the staircase (about 30–60 s for 6 scenes in the sample). |
| Final-frame extract when continuity is off | Non-critical. Runs anyway. |
| Assembly xfade | **Critical path.** 25–56 s measured. |
| QA | Off the path for Studio. |
| Voice TTS | Off the path for Studio. |
| Still-image generation | Off the path for Studio. |
| Frontend poll | Non-critical. ≤ 2.5 s. |

If continuity is turned on, each dependent scene’s Omni create moves onto the critical path in series. That is not what stored projects do.

If the django-q queue already has 6 videos running, queue wait is on the critical path for video 7+.

---

## 22. Current Timeline

Using project 201, the cleanest recent 45 s / 6-scene / concurrency-6 success. Numbers are stored metrics, not estimates. The split inside the 126 s wave is inferred from the staircase and the code order; only the wave total and the per-scene totals are stored.

```
0s
├── snapshot + preflight ...................... 0.01s
├── script phase (caption align / leftover) ... 10.6s
├── storyboard gate ........................... 0.01s
├── Omni wave (6 creates in parallel)
│     first scene recorded done ............... 91s
│     scenes 2–6 finish ~7s apart
│     wave wall ............................... 126s
├── assembly xfade ............................ 33s
└── ready ..................................... 179s   (2 min 59 s)
```

Range on the other healthy 45 s samples in section 2: wave wall 87–241 s, assembly 25–56 s, total 121–275 s.

Historical 8-scene jobs at concurrency 3 (projects 138, 139, 142): `total_generation_ms` 465 s, 522 s, 528 s (7.7–8.8 min), because three waves of blocking creates ran one after another (`launch_ready` waits for the pool before the next wave).

Project 195 recorded `total_generation_ms` 1,705,080 (28.4 min) with `assembly_ms` missing. The scene wave itself was 178 s. The extra ~25 minutes is not explained by the scene rows. Treat it as an outlier stuck after `assembly_started`, not as the typical path.

---

## 23. Optimized Timeline

Not implemented. This is what the same measurements imply if the serial tail and the assembly encode shrink, and if Omni stays at the best observed create time. Omni’s own latency is not something this repo can compress below what Google returns.

Best observed Omni-dominated scene duration in the concurrency-6 sample is about 56 s (project 198, scene-2, before the staircase). Best observed total is 121 s on that same project.

If post-processing of finished scenes overlapped (the pool currently holds every download until the slowest `start()` returns, then encodes in order) and assembly did not re-encode when the per-scene files were already 1080×1920:

```
0s
├── prep ...................................... ~1–11s   (measured)
├── 6 Omni creates together ................... ~56–180s (measured first-scene range)
├── encode/download overlapped with late creates, not after all of them
└── concat without a second full x264 ......... smaller than the measured 25–56s
```

A total under 3 minutes is consistent with the best measured jobs (121 s and 133 s) without a model change. A total under 2 minutes requires Google to return in about a minute and the 25–56 s assembly encode to shrink. That assembly number is measured; removing the xfade re-encode is the only local lever of that size.

Google’s claim that 360p is up to 60% faster than 720p, applied to a 90–180 s create, would be about 35–70 s saved on the wave. That claim is not in this database. The file would still be scaled to 1080×1920.

Parallelizing scenes is already done for the default flag. Another “make scenes parallel” change does not remove the 91–180 s create.

---

## 24. Top 10 Bottlenecks

Impact uses the measured sample. “Estimate” means the staircase inference, not a stored split.

### 1. Blocking Omni `interactions.create`

- File: `backend/ai/providers/google/omni.py`, `GeminiOmniProvider.start`, lines 103–123
- Evidence: scene durations 56–180 s; projects 210 and 213 sat at progress 64 for 15–18 min with zero scene rows; timeout 600 s
- Behavior: one synchronous HTTP call per scene, up to 6 at a time, `background=false`, `store=true`
- Why slow: Google generates the clip on that connection. MISA cannot poll the interaction (comment at lines 105–107).
- Blocking: yes, the qcluster worker and its scene threads
- Parallel already, across scenes in one wave
- Impact: the majority of the 121–275 s success, and the entire 10–15 min tail
- Change: keep the parallel wave; surface progress from the threads; consider `store=false` as Google’s documented faster unary mode; do not expect a local CPU change to move this
- Risk: `store=false` drops later `previous_interaction_id` edits (unused now). Touching auth to re-enable `interactions.get` is what the comment says breaks.

### 2. No progress and no cancel that aborts the HTTP call

- File: `video.py` 575–579 and 737–735; cancel checks are between polls, not inside `create`
- Evidence: cancelled projects remained at progress 64 until the user gave up
- The create timeout is 600 s and is not interrupted by `raise_if_cancelled` until the future returns (`video.py` 728 is inside `as_completed`, so cancel is noticed when a create finishes, not while it blocks)
- Impact: perceived 10–15 min even when the user has hit stop
- Risk of a fix: need a cancellable HTTP timeout on the genai client; a short timeout would fail healthy slow jobs (healthy jobs already reach 180 s)

### 3. Serial FFmpeg after the wave, plus a second xfade encode

- Files: `video.py` 746–1058 and 1310–1361; `ffmpeg.py` 436–499 and 547–584
- Evidence: scene durations increase ~7 s per scene in order; assembly 25–56 s
- Blocking: yes
- The per-scene encode must stay after that scene’s bytes exist. It does not need to wait for the other creates, and the six encodes do not need to be serial.
- Impact: roughly 30–60 s staircase (inferred) + 25–56 s assembly (measured)
- Risk: dropping the 0.28 s crossfade changes the look; parallel encodes raise CPU on a worker that may already be one of six

### 4. Final-frame extract on every scene even when unused

- File: `video.py` 973–975 and 1443–1463, gated only by a successful clip, not by `needs_continuity`
- Evidence: continuity flag is 0 on all recent scenes, and the extract still runs
- Impact: one ffprobe + one frame decode per scene, inside the serial loop. Seconds, not minutes.
- Risk: low to skip when the flag is false

### 5. Bulk multiplies Omni calls on one key

- Files: `studio_bulk.py` 297–298; `settings.py` 197–204
- Evidence: three videos started in the same second (196–198) with parallel windows 191 s, 155 s, 87 s
- 6 workers × 6 scenes = 36 in-flight creates
- Impact: turns a ~90 s wave into a ~180 s wave under contention; video 7 of 10 waits for a worker (another full video duration)
- Risk: lowering video concurrency makes bulk throughput worse while making each video more predictable

### 6. Retries repeat the whole create

- File: `video.py` 749–789
- Up to 3 full creates per scene; silent audio counts
- Impact: worst case adds one or two extra 1–10 min creates for that scene; siblings are kept
- Risk: fewer retries fail more often on transient Google errors

### 7. `store=true` against Google’s faster unary guidance

- File: `omni.py` 111
- Google’s Omni best-practices text: `background=false`, `store=false`, `stream=false` for faster synchronous generation
- Impact: unknown in this database. It is a documented lever on the same model, not a measured one.
- Risk: cannot resume an interaction later. Current code does not resume.

### 8. 720p generation followed by a mandatory 1080×1920 encode

- Files: `.env` `GEMINI_OMNI_RESOLUTION=720p`; `ffmpeg.py` 40–45
- The encode time is inside the staircase and assembly numbers
- Generating 360p might shorten Google time (their claim) and shorten the encode, and it will look worse after the upscale
- Generating 1080p from Omni would likely lengthen Google time (docs call 1080p an upscale) and lengthen the download

### 9. Repeated base64 of the same product and master files

- File: `omni.py` 308–328, called from each `begin`
- Impact: CPU and request body size on the critical request. Not a separate model call. Unmeasured. A multi-megabyte JSON body can slow the POST.
- Risk: low to cache encoded parts for the life of the wave

### 10. SQLite plus full-brief JSON rewrites, and a 20-minute stale killer

- Files: `generation_metrics.py` 28–32; `views.py` 390–398; `settings.py` 96–103
- Impact: short lock waits, not the median. The stale check can declare failure at 20 minutes while `create` is still blocked, because `updated_at` is not touched during the wave.
- Risk: heartbeats that write during the wave must be small, or they add SQLite contention

---

## 25. Under-5-Minute Feasibility

| Scenario | What the evidence supports | Main changes (not done) |
|---|---|---|
| Current, one Studio video, Omni healthy, concurrency 6, 45 s, continuity off | **121–275 s measured** on 10 successes. Median about 194 s. Already under 5 minutes. | None |
| Current tail | **10–18 min observed** while progress stays at 64 (projects 210, 213) and one 28 min outlier (project 195) whose scene wave was only 178 s | The tail is Omni not returning, or a stuck assembly, not the storyboard |
| Safe optimization | A typical job could shed the inferred 30–60 s serial encode tail and part of the 25–56 s second encode, landing nearer the best measured 121–133 s, still bounded by Google | Overlap download/encode with other creates; skip final-frame extract when continuity is off; avoid a second full x264 when clips are already normalized; heartbeat `updated_at` so the UI and the 20-minute stale check match reality |
| Aggressive | Only if Google’s 360p claim holds on this key, or `store=false` is actually faster. Not measured here. Could push a 180 s create down, at a visible quality cost, or not. | `resolution=360p` and/or `store=false`. Do not switch to Veo inside `GeminiOmniProvider.start`; that call would not be valid. |

Under 5 minutes is realistic for the normal single-video path because it is already happening. It is not realistic as a hard guarantee while `interactions.create` is allowed to block for 600 s and bulk can put 36 of those calls on one key.

---

## 26. Optimization Roadmap

Ranked by wall-clock effect on one video, using the measurements above.

**P0**

- Record split timestamps around `start`, first `files.get` that returns ACTIVE, download, and `prepare_scene_clip`. The current `duration_ms` hides the only number that justifies a model change.
- Heartbeat progress during the blocking create so a 15-minute wait is visible as “still waiting on Gemini Omni”, and so cancel/stale logic is not blind.
- Make cancel abort the in-flight HTTP call. Today stop is checked only between creates.

**P1**

- Download and encode a scene as soon as its `start()` future completes, instead of waiting for the slowest future in the pool (`video.py` 725–735 blocks the whole batch).
- Run those encodes with a small pool (2 is enough on one machine) instead of the serial `for job in pending_batch` loop.
- Skip `_extract_final_frame` when `requires_previous_scene_continuity` is false.
- Cap Studio bulk in-flight videos the way path B already caps at 5, so six videos do not each open six Omni calls. This makes one video’s wall clock more stable and makes the last videos in a batch of 10 start sooner only if each video finishes sooner. It does not raise the 6-worker ceiling.

**P2**

- Try `store=false` on one canary project and compare `scene` durations. Google documents it as faster. MISA has not measured it.
- If the product accepts a softer image, try `360p` on a canary. Do not change the default without a side-by-side of the 1080 preview.
- Replace the assembly xfade re-encode with concat-copy when every scene file is already 1080×1920/30 fps/AAC. Measured savings up to ~56 s. Visual change: hard cuts instead of 0.28 s fades.

**P3**

- Cache base64 for the product and master for the wave.
- Delete the dead `family() == "1.x"` branches and the unused `VeoProvider` only as cleanup. That does not change wall-clock time.
- Do not add Celery to go faster. The queue is not the median delay.

---

## 27. Recommended Architecture

Keep one qcluster task per video and one Omni interaction per scene. Change the shape of the wait:

```
POST /generate  →  202  →  qcluster worker
   prep (local)
   submit up to 6 interactions.create calls
        as each returns:
            files.get → download → encode scene     (do not wait for the other creates)
   when all encoded:
        concat (copy if formats match, else one encode)
   write preview, status=ready_for_review
```

Continuity, if a future storyboard sets the flag, stays a chain: scene N+1 is submitted only after scene N’s last frame exists. Independent scenes stay in the pool.

Bulk: one semaphore for “Omni calls in flight” shared by all workers, sized under the Gemini key’s real limit (unknown here; 36 simultaneous calls already correlated with slower waves). Path A should use the same slot counter path B uses, instead of enqueueing every child at once.

Do not put Veo on this path unless product requirements move to last-frame interpolation or extension. The installed code’s reference bundle is an Omni interaction, and Google’s own video overview points that use case at Omni.

---

## 28. Exact Files That Need Changes

When implementation starts, these are the files that own the wall-clock behavior. Not changed in this audit.

| File | Why |
|---|---|
| `backend/ai/providers/google/omni.py` | `start` blocking flags, poll interval, base64, timeout |
| `backend/ai/services/video.py` | `_create_videos` pool barrier, serial post-process, unused frame extract, retry loop, progress heartbeat |
| `backend/ai/services/ffmpeg.py` | per-scene scale and assembly xfade |
| `backend/ai/services/generation_metrics.py` | split timers |
| `backend/ai/services/studio_bulk.py` | path A enqueues every video with no Omni cap |
| `backend/ai/tasks.py` | only if cancel must signal the worker |
| `backend/ai/views.py` | `_fail_if_stale` 20-minute rule vs a heartbeat |
| `frontend/app/brand/(workspace)/studio/page.tsx` | status copy while progress is stuck at 64; poll interval is not the bug |
| `backend/.env` | `GEMINI_OMNI_RESOLUTION`, `VIDEO_SCENE_CONCURRENCY`, `BULK_VIDEO_CONCURRENCY`, `Q_CLUSTER_WORKERS`, `GEMINI_OMNI_POLL_SECONDS` |

Not the first files to touch: `veo.py`, `nano_banana.py`, `qa.py`, `director.py` concept generation. They are off the Studio Generate critical path.

---

## 29. Risks

- Cutting the create timeout below ~180 s will fail jobs that already succeed at 142–181 s (projects 175, 188, 189, 196).
- `360p` plus the existing scale-to-1080 filter will look softer. The business target is a finished 1080×1920 file (`ffmpeg.py` 40–42).
- Removing the crossfade changes the edit. The 0.28 s fade is intentional (`SCENE_TRANSITION_SECONDS`).
- Raising scene concurrency above 6, or video concurrency above 6, on this SQLite box and one API key made overlapping videos slower in the 196–198 trio. More threads are not more throughput.
- Turning continuity on to “improve” consistency would serialize Omni and can push a 6-scene video from ~3 min toward 6× the create time (about 9–18 min at the measured 90–180 s per create).
- `Q_CLUSTER.max_attempts` is 2 with a 7200 s timeout. A hung task can be delivered again and start a second wave of Omni calls for the same project.
- `_fail_if_stale` can mark a job failed at 20 minutes while the thread is still inside `create`.

---

## 30. Final Conclusion

MISA does not generate a Studio video by walking scenes one after another, and it does not use Veo. It submits up to six blocking Gemini Omni 1.1 Flash calls together, then downloads and re-encodes the clips one by one, then crossfades them into a 1080×1920 file. Preparation, stills, voice, and QA are not on that clock.

Successful 45-second videos in the database already finish in about 2 to 4.6 minutes. The 10–15 minute experience is the same code when `interactions.create` does not return: the UI stays at 64%, cancel does not abort the socket, and the client will wait up to 10 minutes per attempt. Bulk makes that worse by running several of those waves on one key and six workers.

The first change that matches the evidence is instrumentation that splits Omni wait from file poll, download, and FFmpeg, plus removing the barrier that holds finished scenes until the slowest create returns. A model swap to Veo Fast is a different API, is not wired, and is not justified by a latency number in this system.

---

## Direct answers

1. **Why does generation take so long?** Because each scene blocks inside `GeminiOmniProvider.start` → `interactions.create` to `gemini-omni-1.1-flash` until Google returns the file (timeout 600 s). Six of those run together. After they return, FFmpeg re-encodes each clip and then crossfades the film (measured 25–56 s). When Google is slow, the worker sits at progress 64 with no further writes. That is the 15–18 minute cancelled jobs 210 and 213.

2. **Single biggest bottleneck?** The blocking Omni create in `omni.py` lines 103–123, called from `begin` in `video.py` lines 648–656.

3. **Scenes sequential or parallel?** Parallel for the default Studio storyboard. `requires_previous_scene_continuity` is false in the database, and `_create_videos` submits up to 6 `start()` calls in one `ThreadPoolExecutor` (`video.py` 707–735).

4. **If parallel, what concurrency?** 6 scene calls per video (`VIDEO_SCENE_CONCURRENCY=6`). Post-processing of those 6 is serial. Across videos, qcluster runs 6 videos (path A) or bulk `advance` runs 5 (path B).

5. **If sequential, why?** They are sequential only when `requires_previous_scene_continuity` is true: `predecessor_ready` waits until the previous scene is in `done_ids` (`video.py` 696–705). Current storyboards do not set that flag (`director.py` 1234–1235). Historical 8-scene jobs were also wave-sequential in groups of 3 because concurrency was 3.

6. **Can independent scenes run concurrently?** They already do, up to 6. All 6 current scenes are independent. An 8th scene would wait for a slot. A continuity chain cannot.

7. **Does bulk parallelize videos?** Yes, with a cap. Studio bulk enqueues every child at once and django-q runs 6. Bulk Studio starts at most 5 and refills when one `run()` finishes (`bulk_studio.py` 694–724). It is not one-video-after-another, and it is not unlimited.

8. **What happens when one scene fails?** That scene is marked failed and added to `done_ids`. Other scenes in the wave continue. After the wave, Studio raises and `run()` marks the project failed (`video.py` 1081–1091, 159–166). The good clips remain.

9. **Does failure regenerate the entire video?** No. The next `run()` skips scenes that already have a real clip and are not flagged `needs_regeneration` or `failed` (`video.py` 542–550). In-wave retries regenerate only the failed scene, up to 3 Omni creates. Continuity dependents are regenerated only when the flag is true. It is false in stored data.

10. **Time waiting for Google?** Not stored separately. The first scene’s recorded duration is the proxy: about 56–181 s on healthy concurrency-6 jobs, and “still running at 15–18 min” on the cancelled progress-64 jobs. That proxy includes one scene’s download and encode after Google returns.

11. **Time spent polling?** The 5 s `files.get` sleep runs only while the file is not ACTIVE, after `create` has returned. If the first check is ACTIVE, the sleep is 0. Worst extra wait after the file is ready is one 5 s interval. This is not the multi-minute number.

12. **Time spent downloading?** Not stored. It sits inside each scene’s `duration_ms`, after `create` returns and before `record_scene_timing`.

13. **Time in FFmpeg?** Assembly is stored: 25–56 s on the recent 45 s successes. Per-scene encode is not stored alone; the ~6–8 s step between ordered scene durations is the serial post-process, which is mostly that encode plus download.

14. **Time in QA?** Zero on the current Studio path. `run()` skips `_quality` for Studio projects (`video.py` 134–144).

15. **Which Google model is used for the video?** `gemini-omni-1.1-flash` at 720p, via `google-genai` 2.21.0 `interactions.create`. Text side model is `gemini-3.6-flash`. Stills use `gemini-2.5-flash-image` only off this path.

16. **Which models are available to this project?** The Gemini Developer API key plus `google-genai` 2.21.0. Wired and used: Omni 1.1 Flash, Gemini 3.6 Flash, Gemini 2.5 Flash Image. Wired and unused: `veo-3.1-generate-preview` (`VeoProvider`). Documented by Google and callable with the same SDK if the key allows them, but not referenced in MISA: `veo-3.1-fast-generate-preview`, `veo-3.1-lite-generate-preview`, `gemini-omni-flash-preview`. Vertex AI is not configured.

17. **Is there a faster Google model without an unacceptable quality loss?** Not one this code can switch on by renaming a string. Omni 1.1 Flash is already Google’s “fast” video model in their current video overview. Veo 3.1 Fast is a different API and is not measured here. On the same Omni model, Google documents `360p` as up to 60% faster than `720p`, and `store=false` as the faster unary setting. `360p` is then upscaled to 1080×1920 by FFmpeg, so the quality loss is on the delivered file. That speed claim is Google’s, not a MISA timing.

18. **Is 720p available, and would it reduce latency?** 720p is already the request (`GEMINI_OMNI_RESOLUTION=720p`). The delivered file is 1080×1920 because FFmpeg scales it. Dropping the Omni request below 720p might shorten Google time. Raising it to 1080p would not remove the FFmpeg scale and, per Google’s Omni docs, 1080p is an upscale on their side.

19. **Are character or product references causing extra generation time?** They do not trigger extra image-model calls on Studio. They are read and base64-encoded into every scene POST. The master is generated once, earlier, by Nano Banana, and reused. A missing presenter can add one Nano Banana still before the wave (`video.py` 1227–1245).

20. **Top 3 changes by impact?** (1) Stop waiting for the slowest `interactions.create` before downloading and encoding the scenes that already finished, and stop encoding serially. (2) Make the blocked create visible and cancellable so 10–15 min hangs are not a frozen 64% bar; add split timers so the next change is aimed at the real slice. (3) Limit how many Omni calls bulk puts on the one API key at once. A model rename is not in this top 3.

21. **Architecture to reach under 5 minutes?** The current one already does, on the measured median. Hold the line by keeping independent scenes in one wave of 6, overlapping each scene’s download/encode with the other creates, and not serializing scenes with continuity unless the storyboard truly needs the previous frame. Under 5 minutes fails when a single create runs toward its 600 s timeout or when bulk contention stacks those creates. Fix that tail; do not add another pipeline stage.

22. **What to change first?** Split the scene timer in `generation_metrics.py` / `_create_videos` into `submitted`, `create_returned`, `file_active`, `downloaded`, `encoded`, and write a progress heartbeat during `start()`. Without that, every later optimization is aimed at a number the database still does not store. The first behavior change that the existing staircase supports is removing the thread-pool barrier at `video.py` 725–735 so a finished scene is encoded while slower scenes are still inside `interactions.create`.
