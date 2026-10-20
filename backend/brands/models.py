from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Brand(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="brands",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="brands",
    )
    name = models.CharField(max_length=200)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="products",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    product_url = models.URLField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Legacy catalog commission as a percentage of price (0–100).",
    )
    commission_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Fixed agent commission in currency units (e.g. 1.00). Preferred over percentage when set.",
    )
    variants = models.JSONField(default=list, blank=True)
    dimensions = models.CharField(max_length=255, blank=True)
    materials = models.CharField(max_length=255, blank=True)
    offer = models.CharField(max_length=255, blank=True)
    offer_expiry = models.DateField(null=True, blank=True)
    approved_claims = models.JSONField(default=list, blank=True)
    prohibited_claims = models.JSONField(default=list, blank=True)
    certifications = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    shipping_conditions = models.TextField(blank=True)
    known_mistakes = models.JSONField(default=list, blank=True)
    prohibited_representations = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(upload_to="products/%Y/%m/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"Photo for {self.product.name}"


class ProductDemoVideo(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="demo_videos",
    )
    video = models.FileField(upload_to="products/videos/%Y/%m/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"Demo video for {self.product.name}"


class ProductShareLink(models.Model):
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="share_link",
    )
    code = models.CharField(max_length=16, unique=True)
    share_count = models.PositiveIntegerField(default=0)
    open_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.code

    @classmethod
    def generate_code(cls) -> str:
        from brands.codes import allocate_public_code

        return allocate_public_code()


class Team(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        ARCHIVED = "archived", "Archived"

    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["brand", "name"], name="uniq_team_brand_name"),
        ]

    def __str__(self) -> str:
        return f"{self.brand.name} / {self.name}"


class TeamMembership(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        REMOVED = "removed", "Removed"

    class OverrideType(models.TextChoices):
        FIXED = "fixed", "Fixed amount"
        PERCENT = "percent", "Percent of price"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_memberships",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    joined_at = models.DateTimeField(default=timezone.now)
    commission_override_type = models.CharField(
        max_length=16,
        choices=OverrideType.choices,
        blank=True,
    )
    commission_override_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-joined_at"]
        constraints = [
            models.UniqueConstraint(fields=["team", "agent"], name="uniq_team_membership_agent"),
        ]

    def __str__(self) -> str:
        return f"{self.agent} @ {self.team}"

    def has_commission_override(self) -> bool:
        return bool(self.commission_override_type and self.commission_override_value is not None)


class TeamInvitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="invitations")
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_invitations",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_team_invitations",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Invite {self.agent} → {self.team}"

    def is_expired(self) -> bool:
        if self.status == self.Status.EXPIRED:
            return True
        return bool(self.expires_at and timezone.now() >= self.expires_at)


class JoinRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="join_requests",
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="join_requests")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_join_requests",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Join {self.agent} → {self.team}"

    def clean(self):
        if self.status == self.Status.PENDING:
            exists = JoinRequest.objects.filter(
                agent=self.agent,
                team=self.team,
                status=self.Status.PENDING,
            ).exclude(pk=self.pk)
            if exists.exists():
                raise ValidationError("This agent already has a pending request for this team.")


class Campaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        ENDED = "ended", "Ended"

    class CommissionType(models.TextChoices):
        FIXED = "fixed", "Fixed amount"
        PERCENT = "percent", "Percent of price"

    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="campaigns")
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
    )
    content = models.ForeignKey(
        "ai.VideoProject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
        help_text="Optional exported Studio project to distribute. References VideoProject; does not copy files.",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    commission_type = models.CharField(
        max_length=16,
        choices=CommissionType.choices,
        blank=True,
    )
    commission_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

    def has_commission(self) -> bool:
        return bool(self.commission_type and self.commission_value is not None)
