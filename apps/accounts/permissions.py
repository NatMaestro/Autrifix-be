from rest_framework.permissions import BasePermission, SAFE_METHODS

from apps.accounts.models import UserRole


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_superuser or getattr(u, "role", None) == UserRole.ADMIN))


class IsDriver(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and getattr(u, "role", None) == UserRole.DRIVER)


class IsMechanic(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and getattr(u, "role", None) == UserRole.MECHANIC)


class IsDriverOrMechanic(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        return getattr(u, "role", None) in (UserRole.DRIVER, UserRole.MECHANIC)


class ReadOnlyUnlessAdmin(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or getattr(request.user, "role", None) == UserRole.ADMIN)
        )
