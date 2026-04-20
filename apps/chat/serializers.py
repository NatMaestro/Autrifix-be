from rest_framework import serializers

from apps.chat.models import ChatMessage, ChatRoom


class ChatMessageSerializer(serializers.ModelSerializer):
    sender = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ChatMessage
        fields = ("id", "sender", "body", "image", "created_at")
        read_only_fields = ("id", "sender", "created_at")


class ChatRoomSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)

    class Meta:
        model = ChatRoom
        fields = ("id", "job", "messages", "created_at")
        read_only_fields = fields


class ChatRoomListSerializer(serializers.ModelSerializer):
    service_request_id = serializers.UUIDField(source="job.service_request_id", read_only=True)
    contact_name = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    last_message_at = serializers.SerializerMethodField()

    def get_contact_name(self, obj: ChatRoom) -> str:
        user = self.context.get("request").user if self.context.get("request") else None
        if user and getattr(user, "role", None) == "driver":
            mechanic = getattr(obj.job, "mechanic", None)
            if mechanic:
                if mechanic.business_name:
                    return mechanic.business_name
                mech_user = getattr(mechanic, "user", None)
                if mech_user:
                    full = f"{mech_user.first_name or ''} {mech_user.last_name or ''}".strip()
                    if full:
                        return full
        if user and getattr(user, "role", None) == "mechanic":
            driver = getattr(getattr(obj.job, "service_request", None), "driver", None)
            if driver:
                if driver.display_name:
                    return driver.display_name
                d_user = getattr(driver, "user", None)
                if d_user:
                    full = f"{d_user.first_name or ''} {d_user.last_name or ''}".strip()
                    if full:
                        return full
        return "Support contact"

    def get_last_message(self, obj: ChatRoom) -> str | None:
        last = obj.messages.order_by("-created_at").first()
        if not last:
            return None
        return (last.body or "").strip() or ("[image]" if last.image else None)

    def get_last_message_at(self, obj: ChatRoom):
        last = obj.messages.order_by("-created_at").first()
        return last.created_at if last else None

    class Meta:
        model = ChatRoom
        fields = (
            "id",
            "job",
            "service_request_id",
            "contact_name",
            "last_message",
            "last_message_at",
            "created_at",
        )
        read_only_fields = fields
