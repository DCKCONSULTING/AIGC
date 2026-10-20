from django.conf import settings
from django.db import models


class LanguageChoice(models.TextChoices):
    CONVERSATIONAL_BM = "conversational_bm", "Conversational BM"
    FORMAL_BM = "formal_bm", "Formal BM"
    BM_ENGLISH = "bm_english", "BM + English"
    ENGLISH = "english", "English"
    CHINESE = "chinese", "Chinese"
    CANTONESE = "cantonese", "Cantonese"
    HOKKIEN = "hokkien", "Hokkien"
    MANDARIN_MY = "mandarin_my", "Malaysian Mandarin"
    TAMIL_MY = "tamil_my", "Malaysian Tamil"


class StyleChoice(models.TextChoices):
    WARM = "warm", "Warm and friendly"
    BOLD = "bold", "Bold and energetic"
    CALM = "calm", "Calm and trusted"
    LUXURY = "luxury", "Premium and refined"


class GenderChoice(models.TextChoices):
    FEMALE = "female", "Female"
    MALE = "male", "Male"
    NEUTRAL = "neutral", "Neutral"


class VideoProjectStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    QUEUED = "queued", "Queued"
    ANALYZING = "analyzing", "Analyzing"
    BRIEF_READY = "brief_ready", "Brief ready"
    SCRIPT_READY = "script_ready", "Script ready"
    PLANNING = "planning", "Planning"
    GENERATING = "generating", "Generating"
    GENERATING_ASSETS = "generating_assets", "Creating images"
    GENERATING_VIDEO = "generating_video", "Creating video"
    GENERATING_VOICE = "generating_voice", "Recording voice"
    PROCESSING = "processing", "Processing"
    ASSEMBLING = "assembling", "Assembling"
    QA = "qa", "Quality check"
    QA_RUNNING = "qa_running", "QA running"
    READY = "ready", "Ready"
    READY_FOR_REVIEW = "ready_for_review", "Ready for review"
    CORRECTING = "correcting", "Correcting"
    APPROVED = "approved", "Approved"
    EXPORTED = "exported", "Exported"
    FAILED = "failed", "Failed"


class QAStatus(models.TextChoices):
    PASSED = "passed", "Passed"
    WARNING = "warning", "Warning"
    FAILED = "failed", "Failed"


class MerchantPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_preference",
    )
    language = models.CharField(
        max_length=32,
        choices=LanguageChoice.choices,
        default=LanguageChoice.CONVERSATIONAL_BM,
    )
    speaking_style = models.CharField(
        max_length=32,
        choices=StyleChoice.choices,
        default=StyleChoice.WARM,
    )
    speaker_gender = models.CharField(
        max_length=16,
        choices=GenderChoice.choices,
        default=GenderChoice.FEMALE,
    )
    voice_name = models.CharField(max_length=80, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"AI preference for {self.user}"


class VideoProject(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="video_projects",
    )
    product = models.ForeignKey(
        "brands.Product",
        on_delete=models.CASCADE,
        related_name="video_projects",
    )
    product_snapshot = models.JSONField(default=dict, blank=True)
    language = models.CharField(
        max_length=32,
        choices=LanguageChoice.choices,
        default=LanguageChoice.CONVERSATIONAL_BM,
    )
    speaking_style = models.CharField(
        max_length=32,
        choices=StyleChoice.choices,
        default=StyleChoice.WARM,
    )
    speaker_gender = models.CharField(
        max_length=16,
        choices=GenderChoice.choices,
        default=GenderChoice.FEMALE,
    )
    duration_seconds = models.PositiveIntegerField(default=45)
    reference_video = models.FileField(
        upload_to="ai/references/%Y/%m/",
        blank=True,
    )
    reference_url = models.URLField(blank=True)
    merchant_voice = models.FileField(
        upload_to="ai/voice-notes/%Y/%m/",
        blank=True,
    )
    merchant_instructions = models.TextField(blank=True)
    product_analysis = models.JSONField(default=dict, blank=True)
    reference_analysis = models.JSONField(default=dict, blank=True)
    creative_brief = models.JSONField(default=dict, blank=True)
    script = models.JSONField(default=dict, blank=True)
    shot_plan = models.JSONField(default=dict, blank=True)
    narration = models.JSONField(default=dict, blank=True)
    captions = models.JSONField(default=dict, blank=True)
    qa_results = models.JSONField(default=dict, blank=True)
    qa_status = models.CharField(max_length=16, choices=QAStatus.choices, blank=True)
    status = models.CharField(
        max_length=32,
        choices=VideoProjectStatus.choices,
        default=VideoProjectStatus.DRAFT,
    )
    stage_label = models.CharField(max_length=120, blank=True)
    progress = models.PositiveIntegerField(default=0)
    error_message = models.CharField(max_length=500, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    kalodata_insights = models.JSONField(default=dict, blank=True)
    creative_directions = models.JSONField(default=list, blank=True)
    selected_concept_id = models.CharField(max_length=64, blank=True)
    amendment_recommendations = models.JSONField(default=list, blank=True)
    amendment_history = models.JSONField(default=list, blank=True)
    director_events = models.JSONField(default=list, blank=True)
    tiktok_checks = models.JSONField(default=dict, blank=True)
    google_operation = models.CharField(max_length=255, blank=True)
    provider_request_id = models.CharField(max_length=255, blank=True)
    narration_audio = models.FileField(upload_to="ai/narration/%Y/%m/", blank=True)
    preview_video = models.FileField(upload_to="ai/previews/%Y/%m/", blank=True)
    final_video = models.FileField(upload_to="ai/final/%Y/%m/", blank=True)
    export_file = models.FileField(upload_to="ai/exports/%Y/%m/", blank=True)
    poster = models.ImageField(upload_to="ai/posters/%Y/%m/", blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Video project {self.pk} for {self.product_id}"

    def mark_progress(self, status: str, progress: int, label: str) -> None:
        from ai.services.cancel import GenerationCancelled, cancel_requested

        if cancel_requested(self):
            raise GenerationCancelled("Stopped by you.")
        self.status = status
        self.progress = min(progress, 100)
        self.stage_label = label
        self.error_message = ""
        self.save(
            update_fields=["status", "progress", "stage_label", "error_message", "updated_at"]
        )

    def mark_failed(self, message: str) -> None:
        from ai.services.cancel import CANCEL_MESSAGE, CANCEL_STAGE, cancel_requested

        if cancel_requested(self):
            # Keep the explicit stop state; do not overwrite with a later failure.
            self.status = VideoProjectStatus.FAILED
            self.error_message = CANCEL_MESSAGE
            self.stage_label = CANCEL_STAGE
            self.save(update_fields=["status", "error_message", "stage_label", "updated_at"])
            return
        self.status = VideoProjectStatus.FAILED
        self.error_message = message
        self.stage_label = "Rate limited" if "rate limited" in message.lower() else "Generation failed"
        self.save(update_fields=["status", "error_message", "stage_label", "updated_at"])


class StyleRecipe(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="style_recipes",
    )
    key = models.SlugField(max_length=64)
    name = models.CharField(max_length=120)
    source_project = models.ForeignKey(
        VideoProject,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="saved_styles",
    )
    recipe = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        unique_together = ("owner", "key")

    def __str__(self) -> str:
        return f"{self.key} ({self.owner_id})"


class Scene(models.Model):
    project = models.ForeignKey(
        VideoProject,
        on_delete=models.CASCADE,
        related_name="scenes",
    )
    scene_key = models.CharField(max_length=64)
    order = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=200, blank=True)
    visual = models.TextField(blank=True)
    narration = models.TextField(blank=True)
    caption = models.TextField(blank=True)
    duration = models.FloatField(default=5)
    image = models.ImageField(upload_to="ai/scenes/images/%Y/%m/", blank=True)
    video_clip = models.FileField(upload_to="ai/scenes/clips/%Y/%m/", blank=True)
    audio = models.FileField(upload_to="ai/scenes/audio/%Y/%m/", blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    generation_status = models.CharField(max_length=16, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.CharField(max_length=500, blank=True)
    provider = models.CharField(max_length=40, blank=True)
    provider_request_id = models.CharField(max_length=255, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        unique_together = ("project", "scene_key")

    def __str__(self) -> str:
        return self.scene_key


class VideoAsset(models.Model):
    class Kind(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"
        THUMBNAIL = "thumbnail", "Thumbnail"
        BACKGROUND = "background", "Background"

    project = models.ForeignKey(
        VideoProject,
        on_delete=models.CASCADE,
        related_name="assets",
    )
    scene = models.ForeignKey(
        Scene,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    file = models.FileField(upload_to="ai/assets/%Y/%m/")
    prompt = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class VideoProjectVersion(models.Model):
    project = models.ForeignKey(
        VideoProject,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        unique_together = ("project", "version")


class UsageRecord(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_usage",
    )
    project = models.ForeignKey(
        VideoProject,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_records",
    )
    provider = models.CharField(max_length=40)
    model_name = models.CharField(max_length=80, blank=True)
    operation = models.CharField(max_length=80)
    status = models.CharField(max_length=32, default="succeeded")
    request_id = models.CharField(max_length=255, blank=True)
    cost_amount = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class CharacterStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class MasterReferenceStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class CharacterView(models.TextChoices):
    FRONT = "front", "Front"
    LEFT = "left", "Left"
    RIGHT = "right", "Right"
    UP = "up", "Looking up"
    DOWN = "down", "Looking down"
    OTHER = "other", "Other"


class Character(models.Model):
    """Reusable on-camera identity. Not tied to a product."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="characters",
    )
    brand = models.ForeignKey(
        "brands.Brand",
        on_delete=models.CASCADE,
        related_name="characters",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    gender = models.CharField(max_length=16, choices=GenderChoice.choices)
    appearance_description = models.TextField(blank=True)
    personality_description = models.TextField(blank=True)
    wardrobe_description = models.TextField(blank=True)
    default_language = models.CharField(
        max_length=32,
        choices=LanguageChoice.choices,
        default=LanguageChoice.CONVERSATIONAL_BM,
    )
    default_tone = models.CharField(
        max_length=32,
        choices=StyleChoice.choices,
        default=StyleChoice.WARM,
    )
    default_voice_provider = models.CharField(max_length=40, default="google_tts")
    default_voice_id = models.CharField(max_length=80, blank=True)
    default_voice_name = models.CharField(max_length=80, blank=True)
    status = models.CharField(
        max_length=16,
        choices=CharacterStatus.choices,
        default=CharacterStatus.ACTIVE,
    )
    source_front_image = models.ImageField(upload_to="ai/characters/source/%Y/%m/", blank=True)
    master_reference_image = models.ImageField(upload_to="ai/characters/master/%Y/%m/", blank=True)
    master_reference_status = models.CharField(
        max_length=16,
        choices=MasterReferenceStatus.choices,
        default=MasterReferenceStatus.PENDING,
    )
    master_reference_version = models.PositiveIntegerField(default=0)
    master_reference_prompt = models.TextField(blank=True)
    master_reference_created_at = models.DateTimeField(null=True, blank=True)
    current_master = models.ForeignKey(
        "CharacterMasterReference",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.name


class CharacterReferenceImage(models.Model):
    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name="references",
    )
    image = models.ImageField(upload_to="ai/characters/%Y/%m/")
    view_type = models.CharField(max_length=16, choices=CharacterView.choices, default=CharacterView.FRONT)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]


class CharacterMasterReference(models.Model):
    """One generated master identity image. Regeneration adds a version; videos freeze a version."""

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name="master_versions",
    )
    version = models.PositiveIntegerField()
    image = models.ImageField(upload_to="ai/characters/master/%Y/%m/")
    source_image = models.ImageField(upload_to="ai/characters/source/%Y/%m/", blank=True)
    prompt = models.TextField(blank=True)
    identity_facts = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-version", "-id"]
        constraints = [
            models.UniqueConstraint(fields=("character", "version"), name="character_master_version_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.character_id} v{self.version}"


class VideoCharacterConfig(models.Model):
    """Frozen character settings for one production. Editing the Character later does not rewrite this."""

    project = models.OneToOneField(
        VideoProject,
        on_delete=models.CASCADE,
        related_name="character_config",
    )
    character = models.ForeignKey(
        Character,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="video_configs",
    )
    language = models.CharField(max_length=32, choices=LanguageChoice.choices)
    tone = models.CharField(max_length=32, choices=StyleChoice.choices)
    gender = models.CharField(max_length=16, choices=GenderChoice.choices)
    voice_provider = models.CharField(max_length=40, default="google_tts")
    voice_id = models.CharField(max_length=80, blank=True)
    voice_name = models.CharField(max_length=80, blank=True)
    appearance_snapshot = models.TextField(blank=True)
    identity_snapshot = models.JSONField(default=dict, blank=True)
    reference_snapshot = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Character config for project {self.project_id}"


class SocialPost(models.Model):
    class Platform(models.TextChoices):
        TIKTOK = "tiktok", "TikTok"
        INSTAGRAM = "instagram", "Instagram"
        FACEBOOK = "facebook", "Facebook"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AUTHORIZED = "authorized", "Authorized"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"

    project = models.ForeignKey(
        VideoProject,
        on_delete=models.CASCADE,
        related_name="social_posts",
    )
    platform = models.CharField(max_length=20, choices=Platform.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    caption = models.TextField(blank=True)
    authorized = models.BooleanField(default=False)
    authorized_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    error_message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class BulkGenerationMode(models.TextChoices):
    CHARACTER = "character", "Character variations"
    PRODUCT = "product", "Product variations"
    EXISTING_VIDEO = "existing_video", "Same flow from existing video"
    REFERENCE_LOCATION = "reference_location", "Reuse story, change location"
    REFERENCE_CHARACTER = "reference_character", "Reuse story, change character"


class BulkGenerationStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ANALYZING = "analyzing", "Analyzing"
    PLAN_READY = "plan_ready", "Plan ready"
    QUEUED = "queued", "Queued"
    GENERATING = "generating", "Generating"
    COMPLETED = "completed", "Completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors", "Completed with errors"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class BulkItemStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PLANNED = "planned", "Planned"
    QUEUED = "queued", "Queued"
    GENERATING = "generating", "Generating"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class BulkGeneration(models.Model):
    """Parent batch for Bulk Studio. Child items become normal VideoProjects."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bulk_generations",
    )
    product = models.ForeignKey(
        "brands.Product",
        on_delete=models.CASCADE,
        related_name="bulk_generations",
    )
    character = models.ForeignKey(
        "Character",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_generations",
    )
    mode = models.CharField(max_length=32, choices=BulkGenerationMode.choices)
    title = models.CharField(max_length=160, blank=True)
    language = models.CharField(
        max_length=32,
        choices=LanguageChoice.choices,
        default=LanguageChoice.CONVERSATIONAL_BM,
    )
    speaking_style = models.CharField(
        max_length=32,
        choices=StyleChoice.choices,
        default=StyleChoice.WARM,
    )
    duration_seconds = models.PositiveIntegerField(default=45)
    requested_count = models.PositiveIntegerField(default=10)
    character_ids = models.JSONField(default=list, blank=True)
    locks = models.JSONField(default=dict, blank=True)
    variables = models.JSONField(default=dict, blank=True)
    instruction = models.TextField(blank=True)
    reference_url = models.URLField(blank=True)
    reference_video = models.FileField(upload_to="ai/bulk/references/%Y/%m/", blank=True)
    master_spec = models.JSONField(default=dict, blank=True)
    generation_plan = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=32,
        choices=BulkGenerationStatus.choices,
        default=BulkGenerationStatus.DRAFT,
    )
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Bulk {self.pk} {self.mode}"


class BulkGenerationItem(models.Model):
    bulk = models.ForeignKey(
        BulkGeneration,
        on_delete=models.CASCADE,
        related_name="items",
    )
    sequence = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=200, blank=True)
    variation_config = models.JSONField(default=dict, blank=True)
    video_project = models.OneToOneField(
        VideoProject,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_item",
    )
    status = models.CharField(
        max_length=16,
        choices=BulkItemStatus.choices,
        default=BulkItemStatus.DRAFT,
    )
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sequence", "id"]
        unique_together = ("bulk", "sequence")

    def __str__(self) -> str:
        return f"Bulk item {self.bulk_id}/{self.sequence}"
