import hashlib
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserRole(models.TextChoices):
    DRIVER = "driver", _("Driver")
    MECHANIC = "mechanic", _("Mechanic")
    ADMIN = "admin", _("Admin")


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, phone, password, **extra_fields):
        email = extra_fields.get("email")
        if email in ("", None):
            extra_fields["email"] = None
        phone_clean = str(phone).strip() if phone is not None else ""
        phone_val = phone_clean or None
        if not phone_val and not extra_fields.get("email"):
            raise ValueError("Either phone or email is required")
        user = self.model(phone=phone_val, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, phone=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone, password, **extra_fields)

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.ADMIN)
        if extra_fields.get("email") in ("", None):
            extra_fields["email"] = None
        if not phone:
            raise ValueError("Superuser must have a phone set.")
        return self._create_user(phone, password, **extra_fields)


class User(AbstractUser):
    username = None
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(
        _("phone number"),
        max_length=20,
        unique=True,
        db_index=True,
        blank=True,
        null=True,
    )
    email = models.EmailField(_("email address"), blank=True, null=True, unique=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.DRIVER,
        db_index=True,
    )
    is_email_verified = models.BooleanField(default=False)

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        ordering = ["-date_joined"]
        verbose_name = _("user")
        verbose_name_plural = _("users")
        constraints = [
            models.CheckConstraint(
                check=models.Q(phone__isnull=False) | models.Q(email__isnull=False),
                name="accounts_user_phone_or_email",
            ),
        ]

    def __str__(self):
        return self.phone or self.email or str(self.pk)

    @property
    def is_driver(self) -> bool:
        return self.role == UserRole.DRIVER

    @property
    def is_mechanic(self) -> bool:
        return self.role == UserRole.MECHANIC

    @property
    def is_admin_role(self) -> bool:
        return self.role == UserRole.ADMIN


class PhoneOTP(models.Model):
    """One-time codes for phone login — store **hash only**, never plaintext."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["phone", "-created_at"]),
        ]

    def __str__(self):
        return f"OTP({self.phone})"

    @staticmethod
    def hash_code(phone: str, code: str) -> str:
        msg = f"{settings.SECRET_KEY}:{phone}:{code}".encode()
        return hashlib.sha256(msg).hexdigest()

    @classmethod
    def verify_and_consume(cls, phone: str, code: str) -> bool:
        now = timezone.now()
        digest = cls.hash_code(phone, code.strip())
        row = (
            cls.objects.filter(
                phone=phone,
                code_hash=digest,
                consumed_at__isnull=True,
                expires_at__gt=now,
            )
            .order_by("-created_at")
            .first()
        )
        if not row:
            return False
        row.consumed_at = now
        row.save(update_fields=["consumed_at"])
        return True

    @classmethod
    def issue(cls, phone: str, code: str, *, ttl_seconds: int) -> None:
        now = timezone.now()
        cls.objects.filter(phone=phone, consumed_at__isnull=True).update(consumed_at=now)
        expires_at = now + timezone.timedelta(seconds=ttl_seconds)
        cls.objects.create(
            phone=phone,
            code_hash=cls.hash_code(phone, code),
            expires_at=expires_at,
        )
