# MISA video generation architecture

Studio and Bulk Studio render through **exactly one** configured video provider. There is no automatic Omni ↔ Veo ↔ MiniMax ↔ Seedance fallback.

```env
VIDEO_PROVIDER=omni
# VIDEO_PROVIDER=veo
# VIDEO_PROVIDER=minimax
# VIDEO_PROVIDER=seedance
```

| | Omni | Veo 3.1 | MiniMax H3 | Seedance |
| --- | --- | --- | --- | --- |
| Setting | `VIDEO_PROVIDER=omni` | `VIDEO_PROVIDER=veo` | `VIDEO_PROVIDER=minimax` | `VIDEO_PROVIDER=seedance` |
| Model env | `OMNI_MODEL` / `GEMINI_OMNI_MODEL` | `VEO_MODEL` | `MINIMAX_VIDEO_MODEL` | `SEEDANCE_MODEL` |
| Default model | `gemini-omni-1.1-flash` | `veo-3.1-generate-preview` | `MiniMax-H3` | `dreamina-seedance-2-5-260628` |
| Fast model (latency) | — | — | — | `dreamina-seedance-2-0-fast-260128` |
| API | Interactions `create` | `models.generate_videos` + poll | `POST /v2/video_generation` + query | ModelArk `POST /contents/generations/tasks` + poll |
| Clip length | 3–10s hops | 8s + 7s extend | 4–15s / 5–15s | **2.5: 4–30s** / **2.0-fast: 4–15s** (fewest clips) |
| Continuity | `previous_interaction_id` | previous Veo video URI | last frame → first_frame | last_frame_url or extracted frame → first_frame |
| Cap | 40s chain then join | 148s | 150s | 120s |
| References | up to 4 | up to 3 | ≤4 sent (API ≤9) | ≤4 sent (API allows more) |
| Native audio | yes | yes | yes | `generate_audio=true` |
| Concurrency | `OMNI_MAX_IN_FLIGHT=3` | `VEO_MAX_IN_FLIGHT=3` | `MINIMAX_MAX_IN_FLIGHT=3` | `SEEDANCE_MAX_IN_FLIGHT=3` |
| Timeout | `OMNI_REQUEST_TIMEOUT_SECONDS=300` | `VEO_OPERATION_TIMEOUT_SECONDS=900` | `MINIMAX_OPERATION_TIMEOUT_SECONDS=900` | `SEEDANCE_OPERATION_TIMEOUT_SECONDS=1800` |
| Priority | — | — | — | `SEEDANCE_PRIORITY` 0–9 (queue order only) |
| 429 | `RATE_LIMITED`, no fallback | same | same | same |

A 429 from the active provider fails the job. It never starts another provider.

## Provider flow

```text
                    VIDEO_PROVIDER
                         │
     ┌───────────┬───────┼───────┬───────────┐
     │           │       │       │           │
   omni         veo   minimax  seedance
     │           │       │       │
 GeminiOmni   VeoProvider MiniMax  SeedanceProvider
     │           │       │       │
 Interactions generateVideos /v2/*  ModelArk tasks
     │           │       │       │
 3–10s hops   8+7s     ≤15s    ≤30s fewest clips
     │           │       │       │
     └───────────┴───────┼───────┴───────────┘
                         │
                      MP4 → ffprobe → captions → COMPLETED
```

Seedance duration examples (2.5): 15=one 15s clip; 30=one 30s clip; 45=30+15; 60=30+30.
Seedance duration examples (2.0-fast): 15=one 15s clip; 30=15+15; 45=15×3; 60=15×4.
Seedance duration examples (1.5-pro): max 12s per clip; 15≈12+4 plan; not suitable for single-clip 30/60s films.

Measured on this account (ap-southeast-1), 4s T2V, `720p`, `generate_audio=true`:

| Model | Activated | priority | API wall (`created_at→updated_at`) |
| --- | --- | --- | --- |
| `dreamina-seedance-2-5-260628` | yes | 0 | ≈1619s (first live test) |
| `dreamina-seedance-2-5-260628` | yes | 9 | ≈227s (later probe) |
| `seedance-1-5-pro-251215` | yes | 0 | ≈47s |
| `dreamina-seedance-2-0-fast-260128` | **no** | — | Console activation required |

Download/local overhead is ~1s. Client polling cannot meet Studio latency targets when 2.5 wall time is minutes. Activate `dreamina-seedance-2-0-fast-260128` (or use retiring `seedance-1-5-pro-251215` for short clips) for lower latency.

Veo duration examples: 15=8+7; 30=8+7×4=36 then trim to 30; 45=50 then trim; 60=64 then trim.

Shared Studio work stays shared: brief, prompt, references, job state, progress, ffprobe, captions, validation, metrics, cleanup, cancellation. Duration planning and API calls stay inside each provider.

There is no automatic Omni ↔ Veo ↔ MiniMax ↔ Seedance fallback. A 429 from the active provider fails the job and releases the worker. Another provider is not started.

## Veo duration

Studio Veo generation is one continuous chain. It does not generate one Veo clip per storyboard scene.

| Requested | Veo plan |
| --- | --- |
| ≤8s | generate 8s, trim if shorter |
| 15s | 8 + 7 |
| 30s | 8 + 7×4 = 36, trim to 30 |
| 45s | 8 + 7×6 = 50, trim to 45 |
| 60s | 8 + 7×8 = 64, trim to 60 |
| 148s | 8 + 7×20 |
| >148s | rejected (`INVALID_DURATION`) |

Do not send `durationSeconds=15/30/45/60` to Veo. Initial generation is 8 seconds because MISA uses reference images. Each extension adds 7 seconds and must pass the previous Veo-generated `Video` URI (`operation.response.generated_videos[0].video`), not a local MP4 with `mime_type`/`encoding`. The Gemini Developer API does not accept video bytes on extend. At most 3 reference images are sent (character, product, style). Native audio stays on. There is no second TTS track.

Veo concurrency is `VEO_MAX_IN_FLIGHT` (default 3). Each create and each extension takes one slot. Operation polling is bounded by `VEO_OPERATION_TIMEOUT_SECONDS` (default 900).

## Omni flow

Studio and Bulk Studio with `VIDEO_PROVIDER=omni` render with `gemini-omni-1.1-flash` through the Interactions API. Omni returns an MP4 that already contains speech. MISA stores that file, probes it, and does only the post-processing the product still needs.

## Final flow

```text
                MISA VIDEO GENERATION

                    User
                      │
                      ▼
                Create Video
                      │
                      ▼
               Build Creative Brief
                      │
                      ▼
             Prepare References ONCE
                      │
                      ▼
              Build ONE Omni Prompt
                      │
                      ▼
        Gemini Omni 1.1 Flash
                      │
             ┌────────┴────────┐
             │                 │
       Single generation    Extension
       if supported         if required
             │                 │
             └────────┬────────┘
                      ▼
                  MP4 + AUDIO
                      │
                      ▼
                URI Download
                      │
                      ▼
                Lightweight Probe
                      │
                      ▼
          Only Required Post-Processing
                      │
                      ▼
                 Final MP4
                      │
                      ▼
             Async Optional QA
```

The production Studio path is:

```text
                    MISA STUDIO

                        │
                        ▼
                 Creative Brief
                        │
                        ▼
              Prepare References Once
                        │
                        ▼
                 Build Film Prompt
                        │
                        ▼
              ┌─────────────────────┐
              │   Duration Planner  │
              └─────────────────────┘
                        │
             ┌──────────┴───────────┐
             │                      │
          ≤40 seconds           >40 seconds
             │                      │
             ▼                      ▼
       ONE Omni Chain         Chain A + Chain B
             │                      │
             │                 Chain A ≤40s
             │                      │
             │                 Chain B is NEW
             │                      │
             └──────────┬───────────┘
                        ▼
                   MP4 + Audio
                        │
                        ▼
                    ffprobe
                        │
                        ▼
              Required Processing Only
                        │
              ┌─────────┴─────────┐
              │                   │
          ≤40 seconds          >40 seconds
              │                   │
              │                FFmpeg join
              │                   │
              └─────────┬─────────┘
                        ▼
                Optional captions
                        │
                        ▼
                   Final MP4
                        │
                        ▼
                Async optional QA
```

```text
CONTINUITY_BOUNDARY = OMNI_MAX_CONTINUOUS_DURATION_SECONDS = 40s
```

One Omni attempt is one HTTP send. The SDK’s default retry loop is turned off for these calls, and a wall-clock watchdog stops the worker at `OMNI_REQUEST_TIMEOUT_SECONDS` plus 5 seconds. A 429 daily-quota response is not retried. Before that change, a 429 with `Retry-After` could sleep for hours inside `interactions.create()` while the socket sat in `CLOSE-WAIT`.

A 60-second video is not one continuous Omni generation. It is a 40-second chain, a new 20-second chain, and a join. The join does not continue the performance. The second chain is a new generation with the same references and a state prompt.

```text
User
 ↓
Frontend Studio Generate  (POST /api/ai/video/<id>/generate/)
 ↓
ProjectGenerateView → django-q2 generate_video_project
 ↓
VideoGenerationService.run
 ↓
generate_continuous_film
 ↓
Gemini Omni interactions.create
    first hop: store=true, references once, global prompt + first time range
    later hops: previous_interaction_id, task=extend, store=true until the last hop
 ↓
output_video URI (inline bytes only if no URI)
 ↓
files download
 ↓
ffprobe (no re-encode)
 ↓
stream-copy join only if Omni returned separate pieces or the length needs two chains
 ↓
stream-copy split into storyboard clips (clean, no burned captions)
 ↓
one caption burn on the preview when caption text exists, audio copied
 ↓
preview MP4
```

Scene regeneration is the exception. `SceneRegenerateView` still calls `_create_videos` for the selected scene and its continuity dependents, then `_assemble` once. It does not rebuild the whole film.

## Omni duration

| | |
| --- | --- |
| Single 60-second generation | NOT SUPPORTED |
| Maximum verified duration of one create | 10 seconds |
| Extension | SUPPORTED |
| Extension maximum | 10 seconds per hop, 40 seconds total per chain |

## Where FFmpeg still runs

| Step | Why |
| --- | --- |
| `concat_clips(..., fade=0)` | Two Omni chains (45s, 60s), or a chain whose files are deltas rather than the growing video. Copy first; re-encode only if copy fails. |
| `burn_captions` | The product still burns the story caption into the preview. One pass, `-c:a copy`, no scale to 1080. |
| `split_copy` | Storyboard playback and scene regeneration need a clip per scene. Stream copy of the clean master. |
| `trim_copy` | Veo chain longer than the product duration (copy first; re-encode if copy cannot produce a valid file). |
| Scene-regeneration `_assemble` | Replacing one scene still has to join the remaining clips once. |

Full-video generation does not scale, normalize, or caption each scene. It does not extract a last frame. It does not run `volumedetect`.

## Audio

The preview is the provider MP4 (Omni or Veo). No TTS track is mixed in. `ffprobe` checks that a video stream and an audio stream exist. A missing audio stream retries the Omni hop once; on Veo it fails as `MISSING_AUDIO`. A caption burn copies the audio stream. `volumedetect` is not used as a generation decision.

## Previous path, and what left it

```text
User
 ↓
Frontend
 ↓
API
 ↓
Django-Q2
 ↓
VideoGenerationService._create_videos
 ↓
one Omni create per storyboard scene (up to 6 at once)
 ↓
download
 ↓
FFmpeg scale / caption / re-encode per scene
 ↓
final-frame extract
 ↓
xfade assemble to 1080×1920
 ↓
preview
```

That path is still the scene-regeneration and non-Studio correction path, without the per-scene scale and without extracting a frame unless a later scene in that job actually needs continuity.

Removed from the full Studio path:

- Treating six storyboard scenes as six videos
- `store=true` on one-shot calls that are never extended
- Per-scene FFmpeg prepare
- Audio measurement that decoded the file
- Final-frame extraction for extension
- Repeating base64 of the same references on every scene
- Studio QA blocking the finished MP4

Bulk still enqueues one job per video. Every Omni create takes `OMNI_MAX_IN_FLIGHT` (default 3). Every Veo create and extension takes `VEO_MAX_IN_FLIGHT` (default 3).

## Progress

Full-video labels follow completed work, not scene counts.

Omni:

- ≤40 seconds: Preparing → Generating continuous film → Finalizing → Ready
- >40 seconds: Preparing → Generating continuous section → Generating final section → Joining → Finalizing → Ready

Veo:

- Preparing references → Generating 8s → Extending to 15s / 22s / … → Finalizing video → Validating video → Ready

The UI shows `stage_label` while status is `generating_video`. Progress does not reach 100% before the final MP4 is validated.

## Failures

| Code | Worker | Omni retry | Veo retry |
| --- | --- | --- | --- |
| `RATE_LIMITED` (HTTP 429) | Released immediately. Job `FAILED` with stage `Rate limited`. | No | No |
| `TIMEOUT` | Released after the watchdog / poll timeout. | No | No |
| `DOWNLOAD_FAILED` | Download retried on Omni. | No (generation) | No |
| `JOIN_FAILED` / `CAPTION_FAILED` / `FFMPEG_FAILED` | Post-process retried on Omni. | No (generation) | No |
| `MISSING_AUDIO` | Omni hop retried once. Veo fails the job. | Yes, once | No |
| `PROVIDER_ERROR` (5xx/network) | Omni hop retried once. Veo fails the job. | Yes, once | No |
| `INVALID_VIDEO` | Job fails. | No | No |
| `CANCELLED` | Worker stops; no further provider calls. | — | — |

A failure never switches `VIDEO_PROVIDER`. Merchant UI uses structured `error_type` first (including `RATE_LIMITED`) and does not hide a rate-limit message just because it mentions a provider name.

`READY_FOR_REVIEW` is set only after the preview MP4 exists.

## Metrics

`creative_brief.generation_metrics` records `video_provider`, `video_model`, requested/generated duration, extension counts, reference count, timestamps, audio present, resolution, fps, and error fields.

Omni also records `architecture=omni_extension_chain`, `omni_chain_count`, `omni_extension_count`, join mode, and one `omni_requests` row per create.

Veo also records `architecture=veo_extension_chain`, `veo_initial_duration`, `veo_extension_count`, `veo_generated_duration`, and `veo_trimmed_duration`.
