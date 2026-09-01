from django.apps import AppConfig


class CustomersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.customers"
    #: Deliberately still ``drivers``. The package was renamed for readability
    #: (ADR-020); the *label* is what Django keys migration history and table names on,
    #: so changing it would orphan applied migrations. Table prefix stays ``drivers_``.
    label = "drivers"
    verbose_name = "Customers"
