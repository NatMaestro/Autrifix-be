from django.apps import AppConfig


class MechanicsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mechanics"
    label = "mechanics"

    def ready(self):
        from apps.mechanics import signals  # noqa: F401
