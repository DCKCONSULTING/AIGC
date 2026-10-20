from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from datetime import timedelta

from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsBrandOwner
from ai.exceptions import GoogleProviderError, MissingAPIKeyError, ProviderError
from ai.models import GenderChoice, MerchantPreference, VideoAsset, VideoProject, VideoProjectStatus
from ai.models import SocialPost, UsageRecord
from ai.providers.intelligence import IntelligenceClient
from ai.providers.intelligence import require_intelligence
from ai.providers.google.omni import require_omni_key
from ai.serializers import (
    MerchantPreferenceSerializer,
    VideoLibrarySerializer,
    VideoProjectSerializer,
    VideoStatusSerializer,
)
from ai.services.director import media_exists
from ai.services.ffmpeg import FFmpegError, export_vertical
from ai.services.product import ProductAnalysisService
from ai.services.qa import QAService
from ai.services.reference import ReferenceAnalysisService
from ai.services.script import ScriptService
from ai.services.snapshots import generation_blocker, product_snapshot
from ai.services.correction import CorrectionService
from ai.tasks import enqueue_missing_video_posters, enqueue_video_correction, enqueue_video_generation
from brands.models import Product

logger = logging.getLogger(__name__)


def _error_response(exc: Exception):
    if isinstance(exc, MissingAPIKeyError):
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if isinstance(exc, (GoogleProviderError, ProviderError)):
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    if isinstance(exc, ValueError):
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    logger.exception("Unhandled AI view error")
    return Response(
        {"detail": "Something went wrong. Please try again."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _owned_product(request, product_id: int) -> Product:
    filters = {"pk": product_id, "brand__owner": request.user}
    return get_object_or_404(
        Product.objects.select_related("brand").prefetch_related("images", "demo_videos"),
        **filters,
    )


def _owned_project(request, pk: int) -> VideoProject:
    filters = {"pk": pk, "owner": request.user}
    return get_object_or_404(
        VideoProject.objects.select_related("product").prefetch_related("scenes", "assets"),
        **filters,
    )


def _clear_file(field) -> None:
    if not field or not getattr(field, "name", ""):
        return
    from ai.services.characters import storage_name_is_character_photo

    # Project assets can point at a character library file. Deleting the project
    # must not remove that photo from the character page.
    if storage_name_is_character_photo(field.name):
        return
    try:
        field.delete(save=False)
    except Exception:
        pass


def _delete_project_media(project: VideoProject) -> None:
    for scene in project.scenes.all():
        _clear_file(scene.image)
        _clear_file(scene.video_clip)
        _clear_file(scene.audio)
    for asset in project.assets.all():
        _clear_file(asset.file)
    for name in (
        "reference_video",
        "merchant_voice",
        "narration_audio",
        "preview_video",
        "final_video",
        "export_file",
    ):
        _clear_file(getattr(project, name))


class PreferenceView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        pref, _ = MerchantPreference.objects.get_or_create(user=request.user)
        return Response(MerchantPreferenceSerializer(pref).data)

    def patch(self, request):
        pref, _ = MerchantPreference.objects.get_or_create(user=request.user)
        serializer = MerchantPreferenceSerializer(pref, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ProductAnalyzeView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request):
        product_id = request.data.get("product_id")
        if not product_id:
            return Response({"detail": "Select a product."}, status=status.HTTP_400_BAD_REQUEST)
        product = _owned_product(request, product_id)
        voice = request.FILES.get("voice")
        try:
            require_intelligence()
            analysis = ProductAnalysisService().analyze(
                product,
                overrides=request.data,
                instructions=request.data.get("instructions") or "",
                voice_bytes=voice.read() if voice else None,
                language=request.data.get("language") or "conversational_bm",
            )
        except Exception as exc:
            return _error_response(exc)
        return Response(analysis)


class ReferenceAnalyzeView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request):
        video = request.FILES.get("video") or request.FILES.get("reference_video")
        reference_url = (request.data.get("reference_url") or "").strip()
        if not video and not reference_url:
            return Response(
                {"detail": "Upload a reference video or paste a video link."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        product = None
        if request.data.get("product_id"):
            product = _owned_product(request, request.data.get("product_id"))
        snapshot = product_snapshot(product) if product else {}
        temp_path = None
        try:
            require_intelligence()
            if video:
                suffix = Path(getattr(video, "name", "reference.mp4")).suffix or ".mp4"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    for chunk in video.chunks():
                        tmp.write(chunk)
                    temp_path = Path(tmp.name)
            analysis = ReferenceAnalysisService().analyze(
                temp_path,
                reference_url=reference_url,
                product_snapshot=snapshot,
            )
        except Exception as exc:
            return _error_response(exc)
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)
        return Response(analysis)


class TranscribeView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request):
        voice = request.FILES.get("voice") or request.FILES.get("audio")
        if not voice:
            return Response(
                {"detail": "Record a voice note first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        temp_path = None
        try:
            require_intelligence()
            suffix = Path(getattr(voice, "name", "voice.webm")).suffix or ".webm"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                for chunk in voice.chunks():
                    tmp.write(chunk)
                temp_path = Path(tmp.name)
            text = IntelligenceClient().transcribe(
                temp_path,
                language=request.data.get("language") or "",
                owner=request.user,
            )
        except Exception as exc:
            return _error_response(exc)
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)
        if not text:
            return Response(
                {"detail": "No speech was recognised in the recording."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"text": text})


class BriefGenerateView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request):
        project_id = request.data.get("project_id")
        if project_id:
            project = _owned_project(request, project_id)
        else:
            product_id = request.data.get("product_id")
            if not product_id:
                return Response({"detail": "Select a product."}, status=status.HTTP_400_BAD_REQUEST)
            product = _owned_product(request, product_id)
            project = _create_project(request, product)
        try:
            require_intelligence()
            if not project.product_analysis:
                project.product_analysis = ProductAnalysisService().analyze(
                    project.product,
                    overrides=project.product_snapshot,
                    instructions=project.merchant_instructions,
                    language=project.language,
                )
            project.creative_brief = ScriptService().build_brief(project)
            project.status = VideoProjectStatus.PLANNING
            project.save()
        except Exception as exc:
            return _error_response(exc)
        return Response(VideoProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class ScriptGenerateView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request):
        project_id = request.data.get("project_id")
        if project_id:
            project = _owned_project(request, project_id)
        else:
            product_id = request.data.get("product_id")
            if not product_id:
                return Response({"detail": "Select a product."}, status=status.HTTP_400_BAD_REQUEST)
            product = _owned_product(request, product_id)
            project = _create_project(request, product)
        try:
            require_intelligence()
            if not project.product_analysis:
                project.product_analysis = ProductAnalysisService().analyze(
                    project.product,
                    overrides=project.product_snapshot,
                    instructions=project.merchant_instructions,
                    language=project.language,
                )
            if not project.creative_brief:
                project.creative_brief = ScriptService().build_brief(project)
            project.script = ScriptService().generate_script(project)
            project.shot_plan = ScriptService().plan_shots(project)
            project.status = VideoProjectStatus.PLANNING
            project.save()
            from ai.services.video import VideoGenerationService

            VideoGenerationService()._sync_scenes(project)
        except Exception as exc:
            return _error_response(exc)
        return Response(VideoProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class VideoListCreateView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        # List every video for the acting owner. X-Acting-Brand selects a company
        # for other screens, but this owner has videos on more than one company.
        # Filtering the library by that header hid every generated video.
        projects = (
            VideoProject.objects.filter(owner=request.user)
            .select_related("product", "character_config")
            .order_by("-updated_at")
        )
        product_id = request.query_params.get("product") or request.query_params.get("product_id")
        if product_id:
            projects = projects.filter(product_id=product_id)
        rows = [_fail_if_stale(project) for project in projects]
        enqueue_missing_video_posters()
        return Response(VideoLibrarySerializer(rows, many=True).data)

    def post(self, request):
        product_id = request.data.get("product_id")
        if not product_id:
            return Response({"detail": "Select a product."}, status=status.HTTP_400_BAD_REQUEST)
        product = _owned_product(request, product_id)
        try:
            require_intelligence()
            require_omni_key()
            blocker = generation_blocker(product_snapshot(product, request.data))
            if blocker:
                return Response({"detail": blocker}, status=status.HTTP_400_BAD_REQUEST)
            project = _create_project(request, product)
            enqueue_video_generation(project.pk)
        except Exception as exc:
            return _error_response(exc)
        return Response(VideoProjectSerializer(project).data, status=status.HTTP_202_ACCEPTED)


class VideoDraftView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request):
        product_id = request.data.get("product_id")
        if not product_id:
            return Response({"detail": "Select a product."}, status=status.HTTP_400_BAD_REQUEST)
        product = _owned_product(request, product_id)
        existing = None
        draft_id = request.data.get("draft_id")
        if draft_id:
            candidate = _owned_project(request, draft_id)
            if candidate.status == VideoProjectStatus.DRAFT:
                existing = candidate
        created = existing is None
        project = _apply_studio_fields(request, product, existing, as_draft=True)
        return Response(
            VideoProjectSerializer(project).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class VideoDetailView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        return Response(VideoProjectSerializer(_fail_if_stale(_owned_project(request, pk))).data)

    def delete(self, request, pk):
        project = _owned_project(request, pk)
        _delete_project_media(project)
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FailedVideoDeleteView(APIView):
    permission_classes = [IsBrandOwner]

    def delete(self, request):
        from ai.services.cancel import _drop_queued_tasks

        projects = list(
            VideoProject.objects.filter(owner=request.user, status=VideoProjectStatus.FAILED)
        )
        ids = [project.pk for project in projects]
        _drop_queued_tasks(ids)
        for project in projects:
            _delete_project_media(project)
            project.delete()
        return Response({"deleted": len(ids)})


_STALE_STATUSES = {
    VideoProjectStatus.QUEUED,
    VideoProjectStatus.ANALYZING,
    VideoProjectStatus.BRIEF_READY,
    VideoProjectStatus.SCRIPT_READY,
    VideoProjectStatus.PLANNING,
    VideoProjectStatus.GENERATING,
    VideoProjectStatus.GENERATING_ASSETS,
    VideoProjectStatus.GENERATING_VIDEO,
    VideoProjectStatus.GENERATING_VOICE,
    VideoProjectStatus.PROCESSING,
    VideoProjectStatus.ASSEMBLING,
    VideoProjectStatus.QA,
    VideoProjectStatus.QA_RUNNING,
    VideoProjectStatus.CORRECTING,
}


def _fail_if_stale(project: VideoProject) -> VideoProject:
    if project.status not in _STALE_STATUSES or not project.updated_at:
        return project
    if timezone.now() - project.updated_at > timedelta(minutes=20):
        if media_exists(project.preview_video):
            project.mark_progress(VideoProjectStatus.READY_FOR_REVIEW, 100, "Video ready")
        else:
            project.mark_failed("Video generation stalled. Please try again.")
        project.refresh_from_db()
    return project


class VideoStatusView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        return Response(VideoStatusSerializer(_fail_if_stale(_owned_project(request, pk))).data)


class VideoCancelView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        from ai.services.cancel import cancel_video_project

        project = _owned_project(request, pk)
        cancel_batch = str(request.data.get("cancel_batch", "1")).lower() not in {"0", "false", "no"}
        stopped = cancel_video_project(project, cancel_batch=cancel_batch)
        primary = next((item for item in stopped if item.pk == project.pk), stopped[0])
        return Response(
            {
                "project": VideoProjectSerializer(primary).data,
                "stopped_ids": [item.pk for item in stopped],
            }
        )


class VideoCorrectView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        project = _owned_project(request, pk)
        voice = request.FILES.get("voice")
        try:
            parsed = CorrectionService().apply(
                project,
                request.data.get("instruction") or "",
                voice_bytes=voice.read() if voice else None,
            )
            enqueue_video_correction(project.pk, parsed)
        except Exception as exc:
            return _error_response(exc)
        project.refresh_from_db()
        return Response(
            {
                "correction": parsed,
                "project": VideoProjectSerializer(project).data,
            }
        )


class VideoRegenerateView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        project = _owned_project(request, pk)
        instruction = (request.data.get("instruction") or request.data.get("amendment") or "").strip()
        if project.status in _STALE_STATUSES:
            return Response(
                {"detail": "This video is already being generated."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if project.status == VideoProjectStatus.DRAFT:
            return Response(
                {"detail": "Generate this video from the studio first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            require_omni_key()
            project.product_snapshot = product_snapshot(project.product, project.product_snapshot)
            blocker = generation_blocker(project.product_snapshot)
            if blocker:
                return Response({"detail": blocker}, status=status.HTTP_400_BAD_REQUEST)
            if not project.scenes.exists():
                if instruction:
                    project.merchant_instructions = "\n".join(
                        part for part in [project.merchant_instructions, instruction] if part
                    )
                from ai.services.cancel import clear_generation_cancel

                clear_generation_cancel(project)
                project.status = VideoProjectStatus.QUEUED
                project.stage_label = "Queued"
                project.progress = 5
                project.error_message = ""
                project.save()
                enqueue_video_generation(project.pk)
            else:
                parsed = CorrectionService().prepare_regenerate(project, instruction)
                enqueue_video_correction(project.pk, parsed)
        except Exception as exc:
            return _error_response(exc)
        project.refresh_from_db()
        return Response(VideoProjectSerializer(project).data, status=status.HTTP_202_ACCEPTED)


class VideoQAView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        project = _owned_project(request, pk)
        try:
            result = QAService().run(project, force=True)
            from ai.services.amendments import AmendmentService

            AmendmentService().recommend(project)
            project.refresh_from_db()
            result["recommendations"] = project.amendment_recommendations
        except Exception as exc:
            return _error_response(exc)
        return Response(result)


class VideoApproveView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        project = _owned_project(request, pk)
        source = project.preview_video
        if not source:
            return Response(
                {"detail": "Generate the video first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from ai.services.director import DirectorService, record_event
        from ai.services.qa import release_blocking_issues
        from ai.services.visual_qa import serious_visual_issues

        checks = (project.qa_results or {}).get("checks") or []
        blocking = (project.qa_results or {}).get("release_blocking") or release_blocking_issues(
            checks, has_preview=bool(project.preview_video)
        )
        if blocking:
            return Response(
                {
                    "detail": blocking[0].get("detail") or "This video has a release-blocking QA failure.",
                    "blocked": True,
                    "requires_confirm": False,
                    "issues": [
                        {
                            "type": item.get("name"),
                            "scene_id": item.get("scene_id"),
                            "message": item.get("detail"),
                            "reason": item.get("reason") or item.get("detail"),
                            "stage": item.get("stage") or "",
                            "confidence": item.get("confidence"),
                            "severity": item.get("severity"),
                            "status": item.get("status"),
                            "frame_url": item.get("frame_url") or "",
                        }
                        for item in blocking
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        serious = [
            item
            for item in serious_visual_issues(checks)
            if item.get("name") not in {issue.get("name") for issue in blocking}
        ]
        confirmed = bool(request.data.get("confirm"))
        if serious and not confirmed:
            return Response(
                {
                    "detail": "Serious visual issues need confirmation before approval.",
                    "requires_confirm": True,
                    "issues": [
                        {
                            "type": item.get("name"),
                            "scene_id": item.get("scene_id"),
                            "message": item.get("detail"),
                            "confidence": item.get("confidence"),
                            "severity": item.get("severity"),
                            "frame_url": item.get("frame_url") or "",
                        }
                        for item in serious
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        DirectorService().approve_scenes(project, all_scenes=True)
        record_event(project, "final_video_approved", {})
        project.status = VideoProjectStatus.APPROVED
        project.approved_at = timezone.now()
        if not project.final_video:
            source.open("rb")
            try:
                project.final_video.save("final.mp4", ContentFile(source.read()), save=False)
            finally:
                source.close()
        project.save()
        return Response(VideoProjectSerializer(project).data)


class VideoExportView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        project = _owned_project(request, pk)
        source = project.final_video or project.preview_video
        if not source:
            return Response(
                {"detail": "Generate and approve the video first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                dest = Path(tmp.name)
            export_vertical(Path(source.path), dest)
            project.export_file.save("export-9x16.mp4", ContentFile(dest.read_bytes()), save=True)
            dest.unlink(missing_ok=True)
            project.status = VideoProjectStatus.EXPORTED
            project.save(update_fields=["status", "export_file", "updated_at"])
        except FFmpegError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return _error_response(exc)
        return Response(VideoProjectSerializer(project).data)


def _create_project(request, product: Product) -> VideoProject:
    return _apply_studio_fields(request, product, as_draft=False)


def _studio_choices(request) -> tuple[str, str, str, int]:
    pref, _ = MerchantPreference.objects.get_or_create(user=request.user)
    language = request.data.get("language") or pref.language
    style = request.data.get("style") or request.data.get("speaking_style") or pref.speaking_style
    gender = (
        request.data.get("gender")
        or request.data.get("speaker_gender")
        or pref.speaker_gender
    )
    from ai.services.durations import supported_duration

    duration = supported_duration(request.data.get("duration_seconds") or 45)
    valid_languages = {choice[0] for choice in MerchantPreference._meta.get_field("language").choices}
    valid_styles = {choice[0] for choice in MerchantPreference._meta.get_field("speaking_style").choices}
    valid_genders = set(GenderChoice.values)
    if language not in valid_languages:
        language = pref.language
    if style not in valid_styles:
        style = pref.speaking_style
    if gender not in valid_genders:
        gender = pref.speaker_gender or GenderChoice.FEMALE
    pref.language = language
    pref.speaking_style = style
    pref.speaker_gender = gender
    pref.save()
    return language, style, gender, duration


def _apply_studio_fields(
    request,
    product: Product,
    project: VideoProject | None = None,
    *,
    as_draft: bool = False,
) -> VideoProject:
    language, style, gender, duration = _studio_choices(request)
    snapshot = product_snapshot(product, request.data)
    if project is None:
        project = VideoProject(owner=request.user, product=product)
    else:
        project.product = product
    project.product_snapshot = snapshot
    project.language = language
    project.speaking_style = style
    project.speaker_gender = gender
    project.duration_seconds = duration
    project.merchant_instructions = request.data.get("instructions") or ""
    if as_draft:
        project.status = VideoProjectStatus.DRAFT
        project.stage_label = "Draft"
        project.progress = 0
        project.error_message = ""
    else:
        if project.pk:
            from ai.services.cancel import clear_generation_cancel

            clear_generation_cancel(project)
        project.status = VideoProjectStatus.QUEUED
        project.stage_label = "Queued"
        project.progress = 2
        project.error_message = ""
    project.save()

    source = None
    source_id = request.data.get("source_id") or (
        None if as_draft else request.data.get("draft_id")
    )
    if source_id:
        source = VideoProject.objects.filter(pk=source_id, owner=request.user).first()
        if source and source.pk == project.pk:
            source = None

    reference = request.FILES.get("reference_video") or request.FILES.get("video")
    if reference:
        project.reference_video.save(reference.name, reference, save=True)
    elif source and source.reference_video:
        project.reference_video = source.reference_video
        project.save(update_fields=["reference_video", "updated_at"])
    reference_url = (request.data.get("reference_url") or "").strip()
    if reference_url:
        project.reference_url = reference_url
        project.save(update_fields=["reference_url", "updated_at"])
    elif source and source.reference_url:
        project.reference_url = source.reference_url
        project.save(update_fields=["reference_url", "updated_at"])
    voice = request.FILES.get("voice")
    if voice:
        project.merchant_voice.save(voice.name, voice, save=True)
    elif source and source.merchant_voice:
        project.merchant_voice = source.merchant_voice
        project.save(update_fields=["merchant_voice", "updated_at"])
    images = list(request.FILES.getlist("reference_image")) + list(
        request.FILES.getlist("reference_images")
    )
    for image in images:
        name = (getattr(image, "content_type", "") or "").lower()
        filename = (getattr(image, "name", "") or "").lower()
        if not (name.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".webp"))):
            continue
        asset = VideoAsset(
            project=project,
            kind=VideoAsset.Kind.IMAGE,
            prompt="style-reference",
            metadata={"style_reference": True},
        )
        asset.file.save(image.name, image, save=True)
    _save_presenter_images(request, project, source)
    return project


def _save_presenter_images(request, project: VideoProject, source: VideoProject | None = None) -> None:
    from ai.services.presenter import PRESENTER_ANGLES, stamp_presenter_reference

    saved = False
    for angle in PRESENTER_ANGLES:
        upload = request.FILES.get(f"presenter_{angle}") or request.FILES.get(f"presenter-{angle}")
        if not upload:
            continue
        name = (getattr(upload, "content_type", "") or "").lower()
        filename = (getattr(upload, "name", "") or "").lower()
        if not (name.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".webp"))):
            continue
        asset = VideoAsset(
            project=project,
            kind=VideoAsset.Kind.IMAGE,
            prompt="presenter-reference",
            metadata={"presenter_reference": True, "presenter_photo": True, "angle": angle},
        )
        asset.file.save(upload.name, upload, save=True)
        saved = True
    extras = list(request.FILES.getlist("presenter_image")) + list(request.FILES.getlist("presenter_images"))
    angles = request.data.getlist("presenter_angle") if hasattr(request.data, "getlist") else []
    for index, image in enumerate(extras):
        name = (getattr(image, "content_type", "") or "").lower()
        filename = (getattr(image, "name", "") or "").lower()
        if not (name.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".webp"))):
            continue
        angle = str(angles[index] if index < len(angles) else PRESENTER_ANGLES[min(index, len(PRESENTER_ANGLES) - 1)])
        asset = VideoAsset(
            project=project,
            kind=VideoAsset.Kind.IMAGE,
            prompt="presenter-reference",
            metadata={"presenter_reference": True, "presenter_photo": True, "angle": angle},
        )
        asset.file.save(image.name, image, save=True)
        saved = True
    if saved:
        brief = dict(project.creative_brief or {})
        presenter = dict(brief.get("presenter") or {})
        presenter["mode"] = "upload"
        brief["presenter"] = presenter
        project.creative_brief = brief
        project.save(update_fields=["creative_brief", "updated_at"])
        stamp_presenter_reference(project)
        return
    if source and source.pk != project.pk:
        copied = False
        for asset in source.assets.filter(kind=VideoAsset.Kind.IMAGE).order_by("id"):
            meta = dict(asset.metadata or {})
            if not (meta.get("presenter_reference") or meta.get("presenter_identity") or meta.get("presenter_photo")):
                continue
            if not asset.file:
                continue
            clone = VideoAsset(
                project=project,
                kind=VideoAsset.Kind.IMAGE,
                prompt=asset.prompt or "presenter-reference",
                metadata={**meta, "presenter_reference": True},
            )
            asset.file.open("rb")
            try:
                clone.file.save(asset.file.name.split("/")[-1], ContentFile(asset.file.read()), save=True)
            finally:
                asset.file.close()
            copied = True
        if copied:
            stamp_presenter_reference(project)


class UsageListView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        records = UsageRecord.objects.filter(owner=request.user)[:50]
        items = [
            {
                "id": row.id,
                "provider": row.provider,
                "operation": row.operation,
                "status": row.status,
                "cost_amount": str(row.cost_amount) if row.cost_amount is not None else "",
                "created_at": row.created_at.isoformat(),
                "project": row.project_id,
            }
            for row in records
        ]
        return Response({"results": items, "count": UsageRecord.objects.filter(owner=request.user).count()})


class SocialPublishView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        project = _owned_project(request, pk)
        platform = (request.data.get("platform") or "").strip()
        authorized = str(request.data.get("authorized") or "").lower() in {"1", "true", "yes"}
        if platform not in SocialPost.Platform.values:
            return Response({"detail": "Choose TikTok, Instagram, or Facebook."}, status=status.HTTP_400_BAD_REQUEST)
        if not authorized:
            return Response(
                {"detail": "Publishing requires your explicit approval."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        post = SocialPost.objects.create(
            project=project,
            platform=platform,
            caption=request.data.get("caption") or "",
            authorized=True,
            authorized_at=timezone.now(),
            status=SocialPost.Status.AUTHORIZED,
        )
        return Response(
            {
                "id": post.id,
                "platform": post.platform,
                "status": post.status,
                "detail": "Saved as authorized. Connect the social account to publish.",
                "project": VideoProjectSerializer(project).data,
            },
            status=status.HTTP_201_CREATED,
        )
