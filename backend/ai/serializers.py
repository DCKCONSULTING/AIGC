from rest_framework import serializers

from ai.services.director import _file_url, infer_scene_status, scene_generation_id

from .models import (
    BulkGeneration,
    BulkGenerationItem,
    Character,
    CharacterMasterReference,
    CharacterReferenceImage,
    GenderChoice,
    LanguageChoice,
    MerchantPreference,
    Scene,
    StyleChoice,
    StyleRecipe,
    VideoAsset,
    VideoCharacterConfig,
    VideoProject,
)


class MerchantPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantPreference
        fields = ("language", "speaking_style", "speaker_gender", "voice_name", "updated_at")
        read_only_fields = ("updated_at",)

    def validate_language(self, value: str) -> str:
        if value not in LanguageChoice.values:
            raise serializers.ValidationError("Choose a supported language.")
        return value

    def validate_speaking_style(self, value: str) -> str:
        if value not in StyleChoice.values:
            raise serializers.ValidationError("Choose a supported style.")
        return value

    def validate_speaker_gender(self, value: str) -> str:
        if value not in GenderChoice.values:
            raise serializers.ValidationError("Choose a supported speaker gender.")
        return value


class SceneSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()
    start_time = serializers.SerializerMethodField()
    end_time = serializers.SerializerMethodField()
    shot_description = serializers.SerializerMethodField()
    presenter_action = serializers.SerializerMethodField()
    camera_framing = serializers.SerializerMethodField()
    camera_movement = serializers.SerializerMethodField()
    lighting = serializers.SerializerMethodField()
    pace = serializers.SerializerMethodField()
    transition = serializers.SerializerMethodField()
    voice_over = serializers.SerializerMethodField()
    on_screen_caption = serializers.SerializerMethodField()
    benefit = serializers.SerializerMethodField()
    approved_claim = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    background = serializers.SerializerMethodField()
    sound_direction = serializers.SerializerMethodField()
    composition = serializers.SerializerMethodField()
    depth_of_field = serializers.SerializerMethodField()
    lens = serializers.SerializerMethodField()
    product_locked = serializers.SerializerMethodField()
    presenter_locked = serializers.SerializerMethodField()
    location_locked = serializers.SerializerMethodField()
    script_locked = serializers.SerializerMethodField()
    caption_locked = serializers.SerializerMethodField()
    scene_locked = serializers.SerializerMethodField()
    scene_status = serializers.SerializerMethodField()
    generation_id = serializers.SerializerMethodField()
    qa_status = serializers.SerializerMethodField()
    qa_results = serializers.SerializerMethodField()
    approved = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()
    pipeline_error = serializers.SerializerMethodField()
    failure_code = serializers.CharField(read_only=True)
    failure_message = serializers.CharField(read_only=True)
    provider = serializers.CharField(read_only=True)
    provider_request_id = serializers.CharField(read_only=True)
    generation_status = serializers.CharField(read_only=True)
    retry_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Scene
        fields = (
            "id",
            "scene_key",
            "order",
            "title",
            "visual",
            "narration",
            "caption",
            "duration",
            "image_url",
            "video_url",
            "audio_url",
            "metadata",
            "start_time",
            "end_time",
            "shot_description",
            "presenter_action",
            "camera_framing",
            "camera_movement",
            "lighting",
            "pace",
            "transition",
            "voice_over",
            "on_screen_caption",
            "benefit",
            "approved_claim",
            "location",
            "background",
            "sound_direction",
            "composition",
            "depth_of_field",
            "lens",
            "product_locked",
            "presenter_locked",
            "location_locked",
            "script_locked",
            "caption_locked",
            "scene_locked",
            "scene_status",
            "generation_id",
            "qa_status",
            "qa_results",
            "approved",
            "error",
            "pipeline_error",
            "failure_code",
            "failure_message",
            "provider",
            "provider_request_id",
            "generation_status",
            "retry_count",
        )
        read_only_fields = fields

    def get_image_url(self, obj: Scene) -> str:
        return _file_url(obj.image)

    def get_video_url(self, obj: Scene) -> str:
        return _file_url(obj.video_clip)

    def get_audio_url(self, obj: Scene) -> str:
        return _file_url(obj.audio)

    def _meta(self, obj: Scene) -> dict:
        return obj.metadata or {}

    def get_start_time(self, obj: Scene) -> float:
        return float(self._meta(obj).get("start_time") or 0)

    def get_end_time(self, obj: Scene) -> float:
        start = self.get_start_time(obj)
        return float(self._meta(obj).get("end_time") or start + float(obj.duration or 0))

    def get_shot_description(self, obj: Scene) -> str:
        return self._meta(obj).get("shot_description") or obj.visual or ""

    def get_presenter_action(self, obj: Scene) -> str:
        return self._meta(obj).get("presenter_action") or ""

    def get_camera_framing(self, obj: Scene) -> str:
        return self._meta(obj).get("camera_framing") or self._meta(obj).get("camera") or ""

    def get_camera_movement(self, obj: Scene) -> str:
        return self._meta(obj).get("camera_movement") or ""

    def get_lighting(self, obj: Scene) -> str:
        return self._meta(obj).get("lighting") or ""

    def get_pace(self, obj: Scene) -> str:
        return self._meta(obj).get("pace") or ""

    def get_transition(self, obj: Scene) -> str:
        return self._meta(obj).get("transition") or ""

    def get_voice_over(self, obj: Scene) -> str:
        return obj.narration or self._meta(obj).get("voice_over") or ""

    def get_on_screen_caption(self, obj: Scene) -> str:
        return obj.caption or self._meta(obj).get("on_screen_caption") or ""

    def get_benefit(self, obj: Scene) -> str:
        return self._meta(obj).get("benefit") or ""

    def get_approved_claim(self, obj: Scene) -> str:
        return self._meta(obj).get("approved_claim") or ""

    def get_location(self, obj: Scene) -> str:
        return self._meta(obj).get("location") or ""

    def get_background(self, obj: Scene) -> str:
        return self._meta(obj).get("background") or ""

    def get_sound_direction(self, obj: Scene) -> str:
        return self._meta(obj).get("sound_direction") or ""

    def get_composition(self, obj: Scene) -> str:
        return self._meta(obj).get("composition") or ""

    def get_depth_of_field(self, obj: Scene) -> str:
        return self._meta(obj).get("depth_of_field") or ""

    def get_lens(self, obj: Scene) -> str:
        return self._meta(obj).get("lens") or ""

    def get_product_locked(self, obj: Scene) -> bool:
        return bool(self._meta(obj).get("product_locked"))

    def get_presenter_locked(self, obj: Scene) -> bool:
        return bool(self._meta(obj).get("presenter_locked"))

    def get_scene_locked(self, obj: Scene) -> bool:
        return bool(self._meta(obj).get("scene_locked"))

    def get_location_locked(self, obj: Scene) -> bool:
        return bool(self._meta(obj).get("location_locked"))

    def get_script_locked(self, obj: Scene) -> bool:
        return bool(self._meta(obj).get("script_locked"))

    def get_caption_locked(self, obj: Scene) -> bool:
        return bool(self._meta(obj).get("caption_locked"))

    def get_scene_status(self, obj: Scene) -> str:
        return infer_scene_status(obj)

    def get_generation_id(self, obj: Scene) -> str:
        return scene_generation_id(self._meta(obj))

    def get_qa_status(self, obj: Scene) -> str:
        return self._meta(obj).get("qa_status") or ""

    def get_qa_results(self, obj: Scene):
        return self._meta(obj).get("qa_results") or []

    def get_approved(self, obj: Scene) -> bool:
        return bool(self._meta(obj).get("approved"))

    def get_error(self, obj: Scene) -> str:
        if getattr(obj, "failure_message", ""):
            return obj.failure_message
        pipe = self._meta(obj).get("pipeline_error") or {}
        return str(pipe.get("detail") or self._meta(obj).get("error") or "").strip()

    def get_pipeline_error(self, obj: Scene) -> dict:
        pipe = dict(self._meta(obj).get("pipeline_error") or {})
        stage = str(pipe.get("stage") or "").strip().lower()
        if stage in {"seedance", "byteplus", "ark", "veo", "gemini", "gemini_omni", "omni"}:
            pipe["stage"] = "video_generation"
            pipe.pop("provider", None)
        return pipe


class VideoAssetSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = VideoAsset
        fields = ("id", "kind", "url", "prompt", "created_at")
        read_only_fields = fields

    def get_url(self, obj: VideoAsset) -> str:
        return _file_url(obj.file)


class VideoProjectSerializer(serializers.ModelSerializer):
    generation_metrics = serializers.SerializerMethodField()
    error_type = serializers.SerializerMethodField()
    scenes = SceneSerializer(many=True, read_only=True)
    assets = VideoAssetSerializer(many=True, read_only=True)
    preview_url = serializers.SerializerMethodField()
    final_url = serializers.SerializerMethodField()
    export_url = serializers.SerializerMethodField()
    poster_url = serializers.SerializerMethodField()
    product_name = serializers.CharField(source="product.name", read_only=True)
    reference_video_url = serializers.SerializerMethodField()
    character_config = serializers.SerializerMethodField()

    class Meta:
        model = VideoProject
        fields = (
            "id",
            "product",
            "product_name",
            "product_snapshot",
            "language",
            "speaking_style",
            "speaker_gender",
            "character_config",
            "duration_seconds",
            "reference_url",
            "reference_video_url",
            "merchant_instructions",
            "kalodata_insights",
            "creative_directions",
            "selected_concept_id",
            "amendment_recommendations",
            "amendment_history",
            "director_events",
            "tiktok_checks",
            "provider_request_id",
            "product_analysis",
            "reference_analysis",
            "creative_brief",
            "script",
            "shot_plan",
            "narration",
            "captions",
            "qa_results",
            "qa_status",
            "status",
            "stage_label",
            "generation_metrics",
            "progress",
            "error_message",
            "error_type",
            "version",
            "scenes",
            "assets",
            "preview_url",
            "final_url",
            "export_url",
            "poster_url",
            "approved_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_error_type(self, obj: VideoProject) -> str:
        return str(((obj.creative_brief or {}).get("provider_error") or {}).get("error_type") or "")

    def get_generation_metrics(self, obj: VideoProject) -> dict:
        return dict((obj.creative_brief or {}).get("generation_metrics") or {})

    def get_preview_url(self, obj: VideoProject) -> str:
        return _file_url(obj.preview_video)

    def get_final_url(self, obj: VideoProject) -> str:
        return _file_url(obj.final_video)

    def get_export_url(self, obj: VideoProject) -> str:
        return _file_url(obj.export_file)

    def get_poster_url(self, obj: VideoProject) -> str:
        return _file_url(obj.poster)

    def get_reference_video_url(self, obj: VideoProject) -> str:
        return _file_url(obj.reference_video)

    def get_character_config(self, obj: VideoProject):
        try:
            config = obj.character_config
        except VideoCharacterConfig.DoesNotExist:
            return None
        return VideoCharacterConfigSerializer(config).data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        raw = instance.kalodata_insights or {}
        data["kalodata_insights"] = {
            "available": bool(raw.get("available")),
            "category_scripts": raw.get("category_scripts") or [],
            "winning_structures": raw.get("winning_structures") or [],
            "shot_plans": raw.get("shot_plans") or [],
            "customer_objections": raw.get("customer_objections") or [],
            "content_ideas": raw.get("content_ideas") or [],
        }
        return data


class VideoLibrarySerializer(VideoProjectSerializer):
    class Meta:
        model = VideoProject
        fields = (
            "id",
            "product",
            "product_name",
            "language",
            "speaking_style",
            "speaker_gender",
            "character_config",
            "duration_seconds",
            "status",
            "stage_label",
            "generation_metrics",
            "progress",
            "error_message",
            "qa_status",
            "selected_concept_id",
            "preview_url",
            "final_url",
            "export_url",
            "poster_url",
            "approved_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_character_config(self, obj: VideoProject):
        try:
            config = obj.character_config
        except VideoCharacterConfig.DoesNotExist:
            return None
        identity = config.identity_snapshot or {}
        return {
            "character": config.character_id,
            "character_name": str(identity.get("name") or ""),
        }

    def to_representation(self, instance):
        return serializers.ModelSerializer.to_representation(self, instance)


class VideoStatusSerializer(serializers.ModelSerializer):
    scene_statuses = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    final_url = serializers.SerializerMethodField()
    export_url = serializers.SerializerMethodField()
    poster_url = serializers.SerializerMethodField()
    generation_metrics = serializers.SerializerMethodField()
    error_type = serializers.SerializerMethodField()

    class Meta:
        model = VideoProject
        fields = (
            "id",
            "status",
            "stage_label",
            "progress",
            "error_message",
            "error_type",
            "qa_status",
            "version",
            "updated_at",
            "preview_url",
            "final_url",
            "export_url",
            "poster_url",
            "scene_statuses",
            "generation_metrics",
        )
        read_only_fields = fields

    def get_error_type(self, obj: VideoProject) -> str:
        return str(((obj.creative_brief or {}).get("provider_error") or {}).get("error_type") or "")

    def get_generation_metrics(self, obj: VideoProject) -> dict:
        return dict((obj.creative_brief or {}).get("generation_metrics") or {})

    def get_preview_url(self, obj: VideoProject) -> str:
        return _file_url(obj.preview_video)

    def get_final_url(self, obj: VideoProject) -> str:
        return _file_url(obj.final_video)

    def get_export_url(self, obj: VideoProject) -> str:
        return _file_url(obj.export_file)

    def get_poster_url(self, obj: VideoProject) -> str:
        return _file_url(obj.poster)

    def get_scene_statuses(self, obj: VideoProject) -> list[dict]:
        return [
            {
                "id": scene.id,
                "scene_key": scene.scene_key,
                "order": scene.order,
                "title": scene.title,
                "status": infer_scene_status(scene),
                "error": scene.failure_message or (scene.metadata or {}).get("error") or "",
                "failure_code": scene.failure_code,
                "failure_message": scene.failure_message,
                "provider": scene.provider,
                "provider_request_id": scene.provider_request_id,
                "retryable": ((scene.metadata or {}).get("pipeline_error") or {}).get("retryable"),
                "pipeline_error": (scene.metadata or {}).get("pipeline_error") or {},
            }
            for scene in obj.scenes.all()
        ]


class StyleRecipeSerializer(serializers.ModelSerializer):
    product_name = serializers.SerializerMethodField()
    source_qa_status = serializers.SerializerMethodField()

    class Meta:
        model = StyleRecipe
        fields = (
            "id",
            "key",
            "name",
            "recipe",
            "source_project",
            "source_qa_status",
            "product_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_product_name(self, obj: StyleRecipe) -> str:
        project = obj.source_project
        if not project:
            return ""
        try:
            return project.product.name
        except Exception:
            return ""

    def get_source_qa_status(self, obj: StyleRecipe) -> str:
        project = obj.source_project
        if not project:
            return ""
        return str(getattr(project, "qa_status", "") or "")


class CharacterMasterSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    source_url = serializers.SerializerMethodField()

    class Meta:
        model = CharacterMasterReference
        fields = ("id", "version", "url", "source_url", "created_at", "approved_at")
        read_only_fields = fields

    def get_url(self, obj: CharacterMasterReference) -> str:
        return _file_url(obj.image)

    def get_source_url(self, obj: CharacterMasterReference) -> str:
        return _file_url(obj.source_image)


class CharacterReferenceSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = CharacterReferenceImage
        fields = ("id", "url", "view_type", "sort_order", "created_at")
        read_only_fields = fields

    def get_url(self, obj: CharacterReferenceImage) -> str:
        return _file_url(obj.image)


class VideoCharacterConfigSerializer(serializers.ModelSerializer):
    character_name = serializers.SerializerMethodField()
    voice_role = serializers.SerializerMethodField()

    class Meta:
        model = VideoCharacterConfig
        fields = (
            "character",
            "character_name",
            "language",
            "tone",
            "gender",
            "voice_provider",
            "voice_id",
            "voice_name",
            "voice_role",
            "appearance_snapshot",
            "identity_snapshot",
            "reference_snapshot",
        )
        read_only_fields = fields

    def get_character_name(self, obj: VideoCharacterConfig) -> str:
        identity = obj.identity_snapshot or {}
        return str(identity.get("name") or "")

    def get_voice_role(self, obj: VideoCharacterConfig) -> str:
        del obj
        from ai.services.characters import VOICE_ROLE

        return VOICE_ROLE


class CharacterSerializer(serializers.ModelSerializer):
    references = CharacterReferenceSerializer(many=True, read_only=True)
    video_count = serializers.SerializerMethodField()
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    preview_url = serializers.SerializerMethodField()
    source_front_url = serializers.SerializerMethodField()
    master_reference_url = serializers.SerializerMethodField()
    latest_master_url = serializers.SerializerMethodField()
    latest_master_version = serializers.SerializerMethodField()
    master_reference_approved = serializers.SerializerMethodField()
    latest_master = serializers.SerializerMethodField()
    front_source_available = serializers.SerializerMethodField()

    class Meta:
        model = Character
        fields = (
            "id",
            "brand",
            "brand_name",
            "name",
            "description",
            "gender",
            "appearance_description",
            "personality_description",
            "wardrobe_description",
            "default_language",
            "default_tone",
            "default_voice_provider",
            "default_voice_id",
            "default_voice_name",
            "status",
            "references",
            "preview_url",
            "source_front_url",
            "front_source_available",
            "master_reference_url",
            "master_reference_status",
            "master_reference_version",
            "master_reference_prompt",
            "master_reference_created_at",
            "master_reference_approved",
            "latest_master_url",
            "latest_master_version",
            "latest_master",
            "video_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_video_count(self, obj: Character) -> int:
        annotated = getattr(obj, "video_count", None)
        if annotated is not None:
            return int(annotated)
        return obj.video_configs.count()

    def get_source_front_url(self, obj: Character) -> str:
        if obj.source_front_image:
            url = _file_url(obj.source_front_image)
            if url:
                return url
        front = next((item for item in obj.references.all() if item.view_type == "front" and _file_url(item.image)), None)
        return _file_url(front.image) if front else ""

    def get_front_source_available(self, obj: Character) -> bool:
        from ai.services.characters import front_source_path

        return front_source_path(obj) is not None

    def get_master_reference_url(self, obj: Character) -> str:
        if obj.current_master_id:
            return _file_url(obj.current_master.image) or _file_url(obj.master_reference_image) or ""
        return _file_url(obj.master_reference_image) or ""

    def get_latest_master(self, obj: Character) -> dict | None:
        latest = obj.master_versions.order_by("-version", "-id").first()
        if not latest:
            return None
        return CharacterMasterSerializer(latest).data

    def get_latest_master_url(self, obj: Character) -> str:
        latest = obj.master_versions.order_by("-version", "-id").first()
        if latest:
            return _file_url(latest.image) or ""
        return ""

    def get_latest_master_version(self, obj: Character) -> int:
        latest = obj.master_versions.order_by("-version", "-id").first()
        return int(latest.version) if latest else 0

    def get_master_reference_approved(self, obj: Character) -> bool:
        from ai.services.master_character import character_is_video_ready

        return character_is_video_ready(obj)

    def get_preview_url(self, obj: Character) -> str:
        approved = self.get_master_reference_url(obj)
        if approved:
            return approved
        latest = self.get_latest_master_url(obj)
        if latest:
            return latest
        source = self.get_source_front_url(obj)
        if source:
            return source
        ref = next((item for item in obj.references.all() if _file_url(item.image)), None)
        if not ref:
            return ""
        return _file_url(ref.image)


class BulkItemProjectSerializer(serializers.ModelSerializer):
    preview_url = serializers.SerializerMethodField()
    poster_url = serializers.SerializerMethodField()
    product_name = serializers.CharField(source="product.name", read_only=True)
    generation_metrics = serializers.SerializerMethodField()

    class Meta:
        model = VideoProject
        fields = (
            "id",
            "status",
            "progress",
            "stage_label",
            "error_message",
            "preview_url",
            "poster_url",
            "product_name",
            "generation_metrics",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_preview_url(self, obj: VideoProject) -> str:
        return _file_url(obj.preview_video)

    def get_poster_url(self, obj: VideoProject) -> str:
        return _file_url(obj.poster)

    def get_generation_metrics(self, obj: VideoProject) -> dict:
        return dict((obj.creative_brief or {}).get("generation_metrics") or {})


class BulkGenerationItemSerializer(serializers.ModelSerializer):
    video_project = BulkItemProjectSerializer(read_only=True)

    class Meta:
        model = BulkGenerationItem
        fields = (
            "id",
            "sequence",
            "title",
            "variation_config",
            "video_project",
            "status",
            "error_message",
            "created_at",
            "completed_at",
        )
        read_only_fields = fields


class BulkGenerationSerializer(serializers.ModelSerializer):
    items = BulkGenerationItemSerializer(many=True, read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    character_name = serializers.SerializerMethodField()
    reference_video_url = serializers.SerializerMethodField()
    completed_count = serializers.SerializerMethodField()
    failed_count = serializers.SerializerMethodField()
    generating_count = serializers.SerializerMethodField()

    class Meta:
        model = BulkGeneration
        fields = (
            "id",
            "mode",
            "title",
            "product",
            "product_name",
            "character",
            "character_name",
            "character_ids",
            "language",
            "speaking_style",
            "duration_seconds",
            "requested_count",
            "locks",
            "variables",
            "instruction",
            "reference_url",
            "reference_video_url",
            "master_spec",
            "generation_plan",
            "status",
            "error_message",
            "completed_count",
            "failed_count",
            "generating_count",
            "items",
            "created_at",
            "started_at",
            "completed_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_character_name(self, obj: BulkGeneration) -> str:
        return obj.character.name if obj.character_id else ""

    def get_reference_video_url(self, obj: BulkGeneration) -> str:
        return _file_url(obj.reference_video)

    def get_completed_count(self, obj: BulkGeneration) -> int:
        items = list(obj.items.all()) if hasattr(obj, "_prefetched_objects_cache") else None
        rows = items if items is not None else obj.items.all()
        return sum(1 for item in rows if item.status == "completed")

    def get_failed_count(self, obj: BulkGeneration) -> int:
        items = list(obj.items.all()) if hasattr(obj, "_prefetched_objects_cache") else None
        rows = items if items is not None else obj.items.all()
        return sum(1 for item in rows if item.status == "failed")

    def get_generating_count(self, obj: BulkGeneration) -> int:
        items = list(obj.items.all()) if hasattr(obj, "_prefetched_objects_cache") else None
        rows = items if items is not None else obj.items.all()
        return sum(1 for item in rows if item.status in {"queued", "generating"})

