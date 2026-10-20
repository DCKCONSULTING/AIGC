from __future__ import annotations

import json

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsBrandOwner
from ai.models import Scene, VideoProject, VideoProjectStatus
from ai.providers.intelligence import require_intelligence
from ai.providers.google.omni import require_omni_key
from ai.serializers import SceneSerializer, VideoProjectSerializer
from ai.services.amendments import AmendmentService
from ai.services.director import DirectorService, record_event
from ai.services.snapshots import generation_blocker, product_snapshot
from ai.tasks import enqueue_scene_regeneration, enqueue_video_generation
from ai.views import (
    _STALE_STATUSES,
    _apply_studio_fields,
    _error_response,
    _owned_product,
    _owned_project,
)


_NON_RETRYABLE = {
    "INVALID_REQUEST",
    "INVALID_DURATION",
    "INVALID_MEDIA",
    "MISSING_CONFIGURATION",
    "UNSUPPORTED_FORMAT",
    "AUTHENTICATION",
    "INVALID_PROMPT",
    "QUOTA",
}


def _deterministic_scene_failure(project: VideoProject) -> dict | None:
    for scene in project.scenes.all():
        code = (scene.failure_code or "").upper()
        if scene.generation_status != "failed" or not code:
            continue
        pipe = (scene.metadata or {}).get("pipeline_error") or {}
        if pipe.get("retryable") is True and code not in _NON_RETRYABLE:
            continue
        if code not in _NON_RETRYABLE and pipe.get("retryable") is not False:
            continue
        return {
            "detail": "This scene cannot be retried until the configuration is fixed.",
            "code": code,
            "failure_message": scene.failure_message,
            "provider": scene.provider or "omni",
            "provider_request_id": scene.provider_request_id,
            "scene_id": scene.pk,
        }
    return None


def _json_value(request, name, default=None):
    value = request.data.get(name, default)
    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _director_project(request, product=None) -> VideoProject:
    project_id = request.data.get("project_id") or request.data.get("id")
    if project_id:
        return _owned_project(request, project_id)
    if not product:
        product_id = request.data.get("product_id")
        if not product_id:
            raise ValueError("Select a product.")
        product = _owned_product(request, product_id)
    draft_id = request.data.get("draft_id")
    existing = None
    if draft_id:
        candidate = _owned_project(request, draft_id)
        if candidate.status == VideoProjectStatus.DRAFT:
            existing = candidate
    return _apply_studio_fields(request, product, existing, as_draft=True)


class CreativeBriefView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request):
        try:
            product_id = request.data.get("product_id")
            if not product_id and not request.data.get("project_id"):
                return Response({"detail": "Select a product."}, status=status.HTTP_400_BAD_REQUEST)
            product = _owned_product(request, product_id) if product_id else None
            project = _director_project(request, product)
            raw = _json_value(request, "creative_brief") or {
                key: request.data.get(key)
                for key in (
                    "objective",
                    "customer",
                    "main_benefit",
                    "original_price",
                    "offer_price",
                    "offer_text",
                    "must_remain_exact",
                    "must_not_show",
                    "platform",
                    "duration",
                    "legacy_instructions",
                )
                if key in request.data
            }
            if request.data.get("duration_seconds") and not raw.get("duration"):
                raw["duration"] = request.data.get("duration_seconds")
            raw = dict(raw or {})
            for key in ("original_price", "offer_price", "offer_text"):
                value = request.data.get(key)
                if value not in (None, "") and not str(raw.get(key) or "").strip():
                    raw[key] = value
            DirectorService().save_brief(project, raw or {})
            project.refresh_from_db()
            from ai.services.characters import sync_project_character

            brief = project.creative_brief or {}
            if "character_id" in (raw or {}) or request.data.get("character_id") not in (None, ""):
                sync_project_character(
                    project,
                    brief.get("character_id"),
                    language=project.language,
                    tone=project.speaking_style,
                    gender=project.speaker_gender,
                    voice_id=str(request.data.get("voice_id") or ""),
                )
                project.refresh_from_db()
        except Exception as exc:
            return _error_response(exc)
        return Response(VideoProjectSerializer(project).data)


class ConceptGenerateView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk=None):
        try:
            require_intelligence()
            project = _owned_project(request, pk) if pk else _director_project(request)
            raw = _json_value(request, "creative_brief")
            if raw:
                DirectorService().save_brief(project, raw)
            count = request.data.get("count") or request.data.get("concept_count")
            DirectorService().generate_concepts(project, count=count)
            project.refresh_from_db()
        except Exception as exc:
            return _error_response(exc)
        return Response(VideoProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class ConceptSelectView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        project = _owned_project(request, pk)
        if project.status in _STALE_STATUSES:
            return Response(
                {"detail": "This video is already being generated."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        concept_id = (request.data.get("concept_id") or "").strip()
        scene_mix = _json_value(request, "scene_mix") or None
        if scene_mix is not None and not isinstance(scene_mix, list):
            return Response(
                {"detail": "Choose scenes from the concepts, or pick one concept."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            DirectorService().select_concept(project, concept_id, scene_mix)
            project.refresh_from_db()
            return Response(VideoProjectSerializer(project).data)
        except Exception as exc:
            return _error_response(exc)


class TimelineView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        project = _owned_project(request, pk)
        director = DirectorService()
        return Response(
            {
                "project_id": project.id,
                "duration_seconds": project.duration_seconds,
                "selected_concept_id": project.selected_concept_id,
                "scenes": [director.scene_to_timeline(scene) for scene in project.scenes.all()],
            }
        )

    def patch(self, request, pk):
        project = _owned_project(request, pk)
        if project.status in _STALE_STATUSES:
            return Response(
                {"detail": "This video is already being generated."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        director = DirectorService()
        try:
            duration = request.data.get("duration_seconds") or request.data.get("duration")
            if duration:
                director.adapt_duration(project, int(duration))
            scene_keys = _json_value(request, "scene_keys")
            if scene_keys:
                director.reorder_scenes(project, list(scene_keys))
            mix = _json_value(request, "scene_mix")
            if mix and request.data.get("concept_id"):
                director.select_concept(project, request.data.get("concept_id"), mix)
            copy = _json_value(request, "copy_scene")
            if copy:
                director.copy_scene_from_concept(
                    project,
                    copy.get("concept_id") or "",
                    copy.get("scene_key") or "",
                    replace_key=copy.get("replace_key") or "",
                )
            project.refresh_from_db()
        except Exception as exc:
            return _error_response(exc)
        return Response(VideoProjectSerializer(project).data)


class SceneDetailView(APIView):
    permission_classes = [IsBrandOwner]

    def _scene(self, request, pk) -> Scene:
        scene = Scene.objects.select_related("project", "project__product").filter(pk=pk).first()
        if not scene:
            from django.http import Http404

            raise Http404()
        _owned_project(request, scene.project_id)
        return scene

    def patch(self, request, pk):
        scene = self._scene(request, pk)
        try:
            DirectorService().update_scene(scene, request.data)
            scene.refresh_from_db()
        except Exception as exc:
            return _error_response(exc)
        return Response(SceneSerializer(scene).data)

    def delete(self, request, pk):
        scene = self._scene(request, pk)
        try:
            DirectorService().delete_scene(scene)
        except Exception as exc:
            return _error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SceneDuplicateView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        scene = SceneDetailView()._scene(request, pk)
        try:
            clone = DirectorService().duplicate_scene(scene)
        except Exception as exc:
            return _error_response(exc)
        return Response(SceneSerializer(clone).data, status=status.HTTP_201_CREATED)


class SceneRegenerateView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        scene = SceneDetailView()._scene(request, pk)
        project = scene.project
        if project.status in _STALE_STATUSES:
            return Response(
                {"detail": "This video is already being generated."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (scene.metadata or {}).get("scene_locked"):
            return Response(
                {"detail": "This scene is locked. Unlock it before regenerating."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (scene.metadata or {}).get("approved") and not request.data.get("confirm"):
            return Response(
                {"detail": "This scene is approved. Confirm before regenerating it."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        code = (scene.failure_code or "").upper()
        pipe = (scene.metadata or {}).get("pipeline_error") or {}
        if code in _NON_RETRYABLE or (scene.generation_status == "failed" and pipe.get("retryable") is False and code):
            return Response(
                {
                    "detail": "This scene cannot be retried until the configuration is fixed.",
                    "code": code,
                    "failure_message": scene.failure_message,
                    "provider": scene.provider or "omni",
                    "provider_request_id": scene.provider_request_id,
                    "scene_id": scene.pk,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            require_omni_key()
            blocker = generation_blocker(project.product_snapshot or product_snapshot(project.product))
            if blocker:
                return Response({"detail": blocker}, status=status.HTTP_400_BAD_REQUEST)
            meta = dict(scene.metadata or {})
            meta["needs_regeneration"] = True
            meta["status"] = "regenerating"
            meta["approved"] = False
            scene.metadata = meta
            scene.save(update_fields=["metadata"])
            from ai.services.director import continuity_dependents, mark_continuity_stale

            stale = mark_continuity_stale(continuity_dependents(project, scene))
            project.status = VideoProjectStatus.CORRECTING
            project.stage_label = f"Regenerating {scene.title or scene.scene_key}"
            project.progress = 12
            project.error_message = ""
            project.save()
            record_event(
                project,
                "scene_regenerated",
                {"scene_key": scene.scene_key, "continuity_dependents": [item.scene_key for item in stale]},
            )
            enqueue_scene_regeneration(project.pk, [scene.pk, *[item.pk for item in stale]])
            project.refresh_from_db()
        except Exception as exc:
            return _error_response(exc)
        return Response(VideoProjectSerializer(project).data, status=status.HTTP_202_ACCEPTED)


class ProjectBulkGenerateView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        project = _owned_project(request, pk)
        try:
            from ai.services.studio_bulk import bulk_generate_from_studio

            created = bulk_generate_from_studio(
                project,
                {
                    "concept_ids": _json_value(request, "concept_ids") or _json_value(request, "concepts"),
                    "character_ids": _json_value(request, "character_ids") or _json_value(request, "characters"),
                    "generate_character": request.data.get("generate_character"),
                    "gender_mode": request.data.get("gender_mode") or request.data.get("gender"),
                    "duration_mode": request.data.get("duration_mode"),
                    "duration_seconds": request.data.get("duration_seconds") or request.data.get("duration"),
                    "count": request.data.get("count") or request.data.get("video_count"),
                    "seedance_model": request.data.get("seedance_model")
                    or request.data.get("video_model")
                    or request.data.get("model"),
                },
            )
        except Exception as exc:
            return _error_response(exc)
        return Response(
            {
                "count": len(created),
                "source_project_id": project.id,
                "projects": VideoProjectSerializer(created, many=True).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ProjectGenerateView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        project = _owned_project(request, pk)
        if project.status in _STALE_STATUSES:
            return Response(
                {"detail": "This video is already being generated."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            require_intelligence()
            require_omni_key()
            if not project.selected_concept_id or not project.scenes.exists():
                return Response(
                    {"detail": "Choose a concept and review the storyboard before generating."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            blocked = _deterministic_scene_failure(project)
            if blocked:
                return Response(blocked, status=status.HTTP_400_BAD_REQUEST)
            project.product_snapshot = product_snapshot(project.product, project.product_snapshot)
            from ai.services.characters import refresh_unfrozen_character_snapshot, sync_project_character
            from ai.services.preflight import preflight_project

            if (project.creative_brief or {}).get("generate_character"):
                sync_project_character(
                    project,
                    None,
                    language=project.language,
                    tone=project.speaking_style,
                    gender=project.speaker_gender,
                )
                project.refresh_from_db()
            refresh_unfrozen_character_snapshot(project)
            project.refresh_from_db()
            preflight_project(project)
            from ai.services.cancel import clear_generation_cancel

            clear_generation_cancel(project)
            from django.utils import timezone as dj_tz

            brief = dict(project.creative_brief or {})
            seedance_model = (
                request.data.get("seedance_model")
                or request.data.get("video_model")
                or request.data.get("model")
            )
            if seedance_model:
                from ai.providers.seedance import resolve_seedance_model

                model_id = resolve_seedance_model(seedance_model)
                brief["seedance_model"] = model_id
                brief["video_model"] = model_id
            brief["queued_at"] = dj_tz.now().isoformat()
            metrics = dict(brief.get("generation_metrics") or {})
            metrics["queued_at"] = brief["queued_at"]
            if brief.get("seedance_model"):
                metrics["video_model"] = brief["seedance_model"]
            brief["generation_metrics"] = metrics
            project.creative_brief = brief
            project.status = VideoProjectStatus.QUEUED
            project.stage_label = "Preparing director plan"
            project.progress = 4
            project.error_message = ""
            project.save()
            enqueue_video_generation(project.pk)
            project.refresh_from_db()
        except Exception as exc:
            return _error_response(exc)
        return Response(VideoProjectSerializer(project).data, status=status.HTTP_202_ACCEPTED)


class AmendmentView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        project = _owned_project(request, pk)
        items = project.amendment_recommendations or AmendmentService().recommend(project)
        return Response({"recommendations": items})

    def post(self, request, pk):
        project = _owned_project(request, pk)
        if project.status in _STALE_STATUSES:
            return Response(
                {"detail": "This video is already being generated."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            if request.data.get("refresh"):
                items = AmendmentService().recommend(project)
                return Response({"recommendations": items, "project": VideoProjectSerializer(project).data})
            ids = _json_value(request, "recommendation_ids") or _json_value(request, "ids") or []
            if request.data.get("apply_all"):
                ids = [item.get("id") for item in (project.amendment_recommendations or []) if item.get("id")]
            edits = _json_value(request, "edits") or {}
            affected = AmendmentService().apply(project, list(ids), edits)
            scene_ids = list(project.scenes.filter(scene_key__in=affected).values_list("pk", flat=True))
            if scene_ids:
                require_omni_key()
                project.status = VideoProjectStatus.CORRECTING
                project.stage_label = "Applying improvements"
                project.progress = 12
                project.error_message = ""
                project.save()
                enqueue_scene_regeneration(project.pk, scene_ids)
            project.refresh_from_db()
        except Exception as exc:
            return _error_response(exc)
        return Response(
            {
                "affected_scenes": affected,
                "project": VideoProjectSerializer(project).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class SceneApproveView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        project = _owned_project(request, pk)
        try:
            scene_ids = _json_value(request, "scene_ids") or []
            all_scenes = bool(request.data.get("all") or request.data.get("all_scenes"))
            DirectorService().approve_scenes(project, [int(item) for item in scene_ids], all_scenes=all_scenes)
            project.refresh_from_db()
        except Exception as exc:
            return _error_response(exc)
        return Response(VideoProjectSerializer(project).data)


def _owned_style(request, pk) -> StyleRecipe:
    from ai.models import StyleRecipe

    recipe = StyleRecipe.objects.filter(pk=pk, owner=request.user).first()
    if not recipe:
        from django.http import Http404

        raise Http404()
    return recipe


class StyleRecipeListView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        from ai.models import StyleRecipe
        from ai.serializers import StyleRecipeSerializer

        recipes = StyleRecipe.objects.filter(owner=request.user)
        return Response(StyleRecipeSerializer(recipes, many=True).data)

    def post(self, request):
        from ai.serializers import StyleRecipeSerializer
        from ai.services.style_recipes import save_recipe

        try:
            project = _owned_project(request, request.data.get("project_id"))
            recipe = save_recipe(
                owner=request.user,
                project=project,
                name=str(request.data.get("name") or ""),
                key=str(request.data.get("key") or ""),
            )
        except Exception as exc:
            return _error_response(exc)
        from ai.serializers import StyleRecipeSerializer as RecipeSerializer

        return Response(RecipeSerializer(recipe).data, status=status.HTTP_201_CREATED)


class StyleRecipeDetailView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        from ai.serializers import StyleRecipeSerializer

        return Response(StyleRecipeSerializer(_owned_style(request, pk)).data)

    def delete(self, request, pk):
        recipe = _owned_style(request, pk)
        recipe.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StyleRecipeApplyView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        from ai.services.style_recipes import apply_recipe_to_project

        recipe = _owned_style(request, pk)
        try:
            project = _director_project(request)
            apply_recipe_to_project(project, recipe, overrides=dict(request.data or {}))
            project.refresh_from_db()
        except Exception as exc:
            return _error_response(exc)
        return Response(VideoProjectSerializer(project).data)


class StyleRecipeBulkView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        from ai.services.style_recipes import MAX_BULK, bulk_create_from_recipe

        recipe = _owned_style(request, pk)
        product_ids = request.data.get("product_ids") or request.data.get("products") or []
        if isinstance(product_ids, str):
            try:
                import json

                product_ids = json.loads(product_ids)
            except json.JSONDecodeError:
                product_ids = [item for item in product_ids.split(",") if item.strip()]
        if not isinstance(product_ids, list) or not product_ids:
            return Response({"detail": "Choose at least one product."}, status=status.HTTP_400_BAD_REQUEST)
        if len(product_ids) > MAX_BULK:
            return Response(
                {"detail": f"Create up to {MAX_BULK} videos at a time."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            products = [_owned_product(request, item) for item in product_ids]
            overrides = {
                key: request.data.get(key)
                for key in (
                    "language",
                    "style",
                    "speaking_style",
                    "gender",
                    "speaker_gender",
                    "location",
                    "background",
                    "ethnicity",
                    "presenter_ethnicity",
                    "ethnicity_custom",
                    "look",
                    "character_id",
                    "voice_id",
                )
                if request.data.get(key)
            }
            presenter = request.data.get("presenter")
            if isinstance(presenter, dict):
                overrides["presenter"] = presenter
            created = bulk_create_from_recipe(
                owner=request.user,
                recipe=recipe,
                products=products,
                overrides=overrides,
            )
        except Exception as exc:
            return _error_response(exc)
        return Response(
            {
                "count": len(created),
                "projects": VideoProjectSerializer(created, many=True).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ProjectSaveStyleView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        from ai.serializers import StyleRecipeSerializer
        from ai.services.style_recipes import save_recipe

        project = _owned_project(request, pk)
        try:
            recipe = save_recipe(
                owner=request.user,
                project=project,
                name=str(request.data.get("name") or ""),
                key=str(request.data.get("key") or ""),
            )
        except Exception as exc:
            return _error_response(exc)
        return Response(StyleRecipeSerializer(recipe).data, status=status.HTTP_201_CREATED)

