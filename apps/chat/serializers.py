from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.chat.models import ChatMessage, ChatRoom


class ChatMessageSerializer(serializers.ModelSerializer):
    sender = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ChatMessage
        fields = ("id", "sender", "body", "image", "created_at")
        read_only_fields = ("id", "sender", "created_at")

    def validate(self, attrs):
        body = (attrs.get("body") or "").strip()
        image = attrs.get("image")
        if not body and not image:
            raise serializers.ValidationError(
                {"body": "Provide a message body, an image, or both."}
            )
        attrs["body"] = body
        return attrs


class ChatRoomSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)

    class Meta:
        model = ChatRoom
        fields = ("id", "job", "messages", "created_at")
        read_only_fields = fields


class ChatRoomListSerializer(serializers.ModelSerializer):
    service_request_id = serializers.UUIDField(source="job.service_request_id", read_only=True)
    job_status = serializers.CharField(source="job.status", read_only=True)
    contact_name = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    last_message_at = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = (
            "id",
            "job",
            "job_status",
            "service_request_id",
            "contact_name",
            "last_message",
            "last_message_at",
            "created_at",
        )
        read_only_fields = fields

    def _viewer(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def get_contact_name(self, obj: ChatRoom) -> str:
        """Name of the *other* participant, resolved from the viewer's side of the job."""
        from apps.jobs.serializers import _person_name

        viewer = self._viewer()
        job = obj.job
        customer = getattr(getattr(job, "service_request", None), "customer", None)
        provider = getattr(job, "provider", None)

        viewer_is_customer = bool(
            viewer and customer and getattr(customer, "user_id", None) == viewer.id
        )
        if viewer_is_customer:
            if provider:
                return provider.business_name or _person_name(
                    getattr(provider, "user", None), "Provider"
                )
            return "Provider"
        if customer:
            return customer.display_name or _person_name(getattr(customer, "user", None), "Customer")
        return "Customer"

    def _last_message(self, obj: ChatRoom):
        # ``messages`` is ordered ascending at the model level, so the prefetch cache can
        # be reused instead of issuing a per-room query.
        messages = list(obj.messages.all())
        return messages[-1] if messages else None

    def get_last_message(self, obj: ChatRoom) -> str | None:
        last = self._last_message(obj)
        if not last:
            return None
        return (last.body or "").strip() or ("[image]" if last.image else None)

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_last_message_at(self, obj: ChatRoom):
        last = self._last_message(obj)
        return last.created_at if last else None
