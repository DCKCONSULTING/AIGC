from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        AGENT = "agent", "Agent"
        PRODUCER = "producer", "Producer"

    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    mobile = models.CharField(max_length=20)
    location = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.AGENT)

    REQUIRED_FIELDS = ["email", "name", "mobile", "location"]

    def __str__(self) -> str:
        return self.username

    @property
    def can_choose_account(self) -> bool:
        return bool(self.is_superuser)
