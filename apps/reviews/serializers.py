from rest_framework import serializers

from apps.core.exceptions import Conflict
from apps.jobs.models import Job, JobStatus
from apps.reviews.models import Review


class ReviewSerializer(serializers.ModelSerializer):
    """A customer's review of the provider who completed their job.

    Eligibility (``specs/011-ratings-reviews.md`` REQ-1): the author must be the job's
    customer, the job must be ``completed``, and one review per job per author.
    """

    job = serializers.PrimaryKeyRelatedField(queryset=Job.objects.all())
    provider = serializers.UUIDField(source="job.provider_id", read_only=True)
    provider_name = serializers.CharField(source="job.provider.business_name", read_only=True)

    class Meta:
        model = Review
        fields = ("id", "job", "provider", "provider_name", "author", "rating", "comment", "created_at")
        read_only_fields = ("id", "author", "created_at")

    def _actor(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def validate_job(self, job: Job):
        actor = self._actor()
        if actor is None:
            raise serializers.ValidationError("Authentication is required.")

        driver_user_id = job.service_request.customer.user_id
        if driver_user_id != actor.id:
            # Same message whether the job is absent or simply not theirs.
            raise serializers.ValidationError("You can only review your own completed jobs.")

        if job.status != JobStatus.COMPLETED:
            raise serializers.ValidationError(
                f"This job is '{job.status}'. Only a completed job can be reviewed."
            )
        return job

    def validate(self, attrs):
        job = attrs.get("job")
        actor = self._actor()
        if job is not None and actor is not None:
            exists = Review.objects.filter(job=job, author=actor)
            if self.instance is not None:
                exists = exists.exclude(pk=self.instance.pk)
            if exists.exists():
                # 409 rather than 400: the request is well-formed, the resource already exists.
                raise Conflict("You have already reviewed this job.")
        return attrs
