from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.notifications import services as notifications
from apps.reviews.models import Review
from apps.reviews.services import recalculate_provider_rating


def _mechanic_id_for(review: Review):
    """Resolve the reviewed provider without exploding on a cascade delete.

    On ``post_delete`` the parent job may already be gone, in which case there is
    nothing left to recalculate.
    """
    try:
        return review.job.provider_id
    except Exception:  # Job already deleted by a cascade
        return None


@receiver(post_save, sender=Review)
def review_saved(sender, instance: Review, created: bool, **kwargs):
    # Recalculated inline rather than on_commit: the aggregate runs in the same
    # transaction as the review, so the cached summary rolls back with it.
    recalculate_provider_rating(_mechanic_id_for(instance))
    if created:
        notifications.notify_review_received(instance)


@receiver(post_delete, sender=Review)
def review_deleted(sender, instance: Review, **kwargs):
    recalculate_provider_rating(_mechanic_id_for(instance))
