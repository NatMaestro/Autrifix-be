from django.contrib import admin

from .models import ChatMessage, ChatRoom


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    inlines = [ChatMessageInline]
