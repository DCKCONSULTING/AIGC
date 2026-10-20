# MISA video generation — optimization plan

This plan was checked against the installed `google-genai` SDK (`VideoResponseFormat`, `VideoConfig.task`, `interactions.create`) and the Gemini Omni documentation saved for this project. It is the decision record for the implementation. No duration below is inferred from a wish.

## Verified Omni limits

Model: `gemini-omni-1.1-flash` through the Interactions API.

| Question | Result |
| --- | --- |
| Single 60-second generation | **NOT SUPPORTED** |
| Maximum duration of one `interactions.create` | **10 seconds** (minimum 3). `response_format.duration` is a string such as `"8s"`. |
| Can duration be requested? | Yes, as that string, inside 3–10 seconds. The SDK type is an optional string, not an integer of 60. |
| Is duration only inferred? | No. MISA sends `duration`. Omni still clamps anything outside 3–10. |
| Video extension | **SUPPORTED** |
| Extension mechanism | `previous_interaction_id` on a later `interactions.create`, with `video_config.task` of `extend`. |
| Extension step | Another **3–10 seconds** appended to the end. |
| Maximum resulting duration of one chain | **40 seconds** |
| Does extension keep native audio and dialogue? | Yes for a model-generated chain continued with `previous_interaction_id`. An uploaded clip cannot gain new speech if someone is already talking. MISA uses the interaction chain, not an upload. |
| Is extension appropriate for MISA? | Yes for 15 and 30 seconds (one chain). 45 and 60 seconds need two chains because 40 seconds is the cap, then one join. |
| `store` | `store=false` is the documented fast path when the interaction will not be continued. `store=true` is required on every call that a later call extends. The last call in a chain uses `store=false`. |

There is no supported `duration=60` parameter. Sending one would be rejected or clamped. It is not sent.

## Chain plan

Storyboard scene counts stay 15→3, 30→5, 45→6, 60→6. Those are edit points, not Omni requests.

| Requested video | Omni calls | Shape |
| --- | --- | --- |
| 15s | 2 | one chain `[10, 5]` |
| 30s | 3 | one chain `[10, 10, 10]` |
| 45s | 5 | `[10, 10, 10, 10]` then `[5]` |
| 60s | 6 | `[10, 10, 10, 10]` then `[10, 10]` |

60 seconds still makes six Omni calls. They are two continuous chains plus one join, not six independent videos. Extensions are sequential, so a 60-second job can take longer on the wall clock than six parallel creates. That tradeoff is accepted because continuity and native audio stay inside Omni.

## Request shape

One-shot (scene regeneration, a single clip):

```python
background=False
store=False
stream=False
response_format={"type": "video", "delivery": "uri", "aspect_ratio": "9:16", "duration": "<3-10>s", "resolution": "720p"}
```

Extension hop (every call except the last in a chain):

```python
background=False
store=True
stream=False
previous_interaction_id="<previous>"
generation_config={"video_config": {"task": "extend"}}
```

720p is Omni's default. 1080p and 4k are provider upscales. MISA does not request them. The file is delivered at Omni's portrait 720p. There is no per-scene scale to 1080×1920.

Reference images are base64-encoded once per job and sent on the first call of each chain. Extension hops do not resend them. The cap remains 4 images.

## What MISA stops doing on the full-video path

- One Omni request per storyboard scene
- Per-scene FFmpeg normalize, scale, caption burn, and re-encode
- Final-frame extraction when the next step is an Omni extension
- `inspect_audio` / `volumedetect` as a reason to regenerate
- A second TTS track
- Studio QA on the critical path (unchanged: Studio already skipped it)

FFmpeg remains for three real jobs: stream-copy join when a chain returns separate pieces or when 45/60 seconds needs two chains; one caption burn on the finished file when caption text exists (`-c:a copy`); stream-copy splits so scene regeneration still has a clip to replace.

## Audio

Omni's MP4 audio is the only voice. After download, `ffprobe` records `audio_present`, `audio_codec`, `duration`, `video_codec`, `resolution`, `fps`, and `file_size`. A video stream with no audio stream is a generation failure and may be retried. A download or FFmpeg failure does not start another Omni call. Missing audio does not start TTS.

## Locked captions

When a scene has `caption_locked`, the prompt for that time range tells Omni to speak the caption exactly and not paraphrase, shorten, translate, or add words.

## Concurrency, retries, cancellation

`OMNI_MAX_IN_FLIGHT` (default 3) wraps `interactions.create` for Studio, scene regeneration, and bulk. Bulk workers can no longer multiply by scene concurrency.

Retries: generation errors that the provider marks retryable, and a missing audio stream, up to 3 creates. Download failures retry the download only. Post-processing failures are `POSTPROCESSING_FAILED` and do not create again. Completed chain files are kept and reused when the storyboard signature matches and the preview was not already saved.

The blocking create timeout is `OMNI_REQUEST_TIMEOUT_SECONDS` (default 300, was 600). A heartbeat updates `updated_at` during the call so the 20-minute stale sweep does not kill a live request. Cancellation is checked between segments. The in-flight HTTP call is not reported as stopped until it returns.

## Progress

Full video: Preparing, Submitting to Gemini Omni, Initial generation, Extension N, Downloading, Finalization, Final validation. Scene numbers are not the progress model. Scene regeneration still uses the scene pool.

## Tests before calling this done

- Chain planner for 15/30/45/60
- Provider: `store=false` by default, `store=true` plus `previous_interaction_id` and `task=extend` for an extension, resolution stays 720p even if 1080p is configured
- A 30-second Studio film makes 3 Omni calls, not 5, and burns captions once
- Existing scene-regeneration tests still call the scene pool
