import hashlib
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.validators import validate_image_size


class UserRole(models.TextChoices):
    """Who someone is on the platform.

    ``customer`` replaced ``driver`` on 2026-08-18: "driver" collided with rideshare apps
    in signup copy, and became actively ambiguous once tow operators — who *are* drivers —
    joined the platform. ``provider`` replaced ``mechanic`` so one role covers mechanics,
    tow operators, and agencies; the specific trade lives on
    ``ProviderProfile.provider_type``. See ADR-020.
    """

    CUSTOMER = "customer", _("Customer")
    PROVIDER = "provider", _("Service provider")
    ADMIN = "admin", _("Admin")


#: Roles a visitor may choose at signup. ``admin`` is never self-assignable.
SIGNUP_ROLE_CHOICES = [choice for choice in UserRole.choices if choice[0] != UserRole.ADMIN]


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
    avatar = models.ImageField(
        upload_to="avatars/", blank=True, null=True, validators=[validate_image_size]
    )
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.CUSTOMER,
        db_index=True,
    )
    is_email_verified = models.BooleanField(default=False)
    #: Set by OTP confirmation. A precondition for provider verification (SPEC-013 REQ-5);
    #: registration collects a phone but does not verify it.
    is_phone_verified = models.BooleanField(default=False)

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
    def is_customer(self) -> bool:
        return self.role == UserRole.CUSTOMER

    @property
    def is_provider(self) -> bool:
        return self.role == UserRole.PROVIDER

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
    def _live_row(cls, phone: str, code: str):
        return (
            cls.objects.filter(
                phone=phone,
                code_hash=cls.hash_code(phone, code.strip()),
                consumed_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )

    @classmethod
    def is_code_valid(cls, phone: str, code: str) -> bool:
        """Is this code currently valid? **Does not consume it.**

        Not named ``check`` — that shadows Django's ``Model.check()`` and breaks the whole
        system-check framework, which pytest does not run but ``manage.py`` does.

        Split out so a caller can validate the code, discover it cannot finish (no role
        chosen for a new account), and refuse *without* destroying the caller's only way
        to retry.
        """
        return cls._live_row(phone, code) is not None

    @classmethod
    def verify_and_consume(cls, phone: str, code: str) -> bool:
        row = cls._live_row(phone, code)
        if not row:
            return False
        row.consumed_at = timezone.now()
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
