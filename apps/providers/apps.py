from django.apps import AppConfig


class ProvidersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.providers"
    #: Deliberately still ``mechanics`` — see CustomersConfig. Table prefix stays
    #: ``mechanics_``.
    label = "mechanics"
    verbose_name = "Service providers"

    def ready(self):
        from apps.providers import signals  # noqa: F401
