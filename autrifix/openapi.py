"""drf-spectacular preprocessing — keep OpenAPI focused on versioned REST routes."""


def preprocessing_filter_api_v1(endpoints):
    """Include only ``/api/v1/...`` paths (excludes ``/admin/``, schema UIs, etc.)."""
    return [
        (path, path_regex, method, callback)
        for path, path_regex, method, callback in endpoints
        if path.startswith("/api/v1/")
    ]
