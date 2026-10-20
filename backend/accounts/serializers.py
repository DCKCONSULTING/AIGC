from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "name",
            "email",
            "mobile",
            "location",
            "role",
            "is_superuser",
        )
        read_only_fields = fields


class ProfileUpdateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password_confirm = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    current_password = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )

    class Meta:
        model = User
        fields = (
            "username",
            "name",
            "email",
            "mobile",
            "location",
            "password",
            "password_confirm",
            "current_password",
        )

    def validate_username(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter a username.")
        qs = User.objects.filter(username__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        qs = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_mobile(self, value: str) -> str:
        value = value.strip()
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) < 8:
            raise serializers.ValidationError("Enter a valid mobile number.")
        return value

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter your full name.")
        return value

    def validate_location(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter your city or country.")
        return value

    def validate(self, attrs):
        password = (attrs.get("password") or "").strip()
        password_confirm = attrs.get("password_confirm") or ""
        current_password = attrs.get("current_password") or ""
        if password or password_confirm:
            if len(password) < 8:
                raise serializers.ValidationError(
                    {"password": "Password must be at least 8 characters."}
                )
            if password != password_confirm:
                raise serializers.ValidationError(
                    {"password_confirm": "Passwords do not match."}
                )
            if not current_password:
                raise serializers.ValidationError(
                    {"current_password": "Enter your current password."}
                )
            if self.instance is None or not self.instance.check_password(
                current_password
            ):
                raise serializers.ValidationError(
                    {"current_password": "Current password is incorrect."}
                )
            attrs["password"] = password
        else:
            attrs.pop("password", None)
            attrs.pop("password_confirm", None)
            attrs.pop("current_password", None)
        return attrs

    def update(self, instance, validated_data):
        validated_data.pop("password_confirm", None)
        validated_data.pop("current_password", None)
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class AccountRegisterSerializer(serializers.ModelSerializer):
    role = User.Role.AGENT
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = (
            "username",
            "name",
            "email",
            "mobile",
            "location",
            "password",
            "password_confirm",
        )

    def validate_username(self, value: str) -> str:
        value = value.strip()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_mobile(self, value: str) -> str:
        value = value.strip()
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) < 8:
            raise serializers.ValidationError("Enter a valid mobile number.")
        return value

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter your full name.")
        return value

    def validate_location(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter your city or country.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        password = validated_data.pop("password")
        user = User(role=self.role, **validated_data)
        user.set_password(password)
        user.save()
        return user


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = attrs["identifier"].strip()
        password = attrs["password"]
        user = authenticate(
            self.context.get("request"),
            username=identifier,
            password=password,
        )
        if user is None:
            raise serializers.ValidationError(
                "Invalid username/email or password."
            )

        if user.can_choose_account:
            attrs["user"] = user
            return attrs

        expected_role = self.context.get("expected_role")
        if expected_role and user.role != expected_role:
            if user.role == User.Role.PRODUCER:
                raise serializers.ValidationError(
                    "This is a brand account. Please use brand log in."
                )
            raise serializers.ValidationError(
                "This is an agent account. Please use agent log in."
            )

        attrs["user"] = user
        return attrs
