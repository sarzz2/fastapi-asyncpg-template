"""
Serialization utility functions.
"""

from typing import Any


def json_serialize_safe(obj: Any) -> Any:
    """
    Recursively convert non-JSON serializable objects to string representations.

    Args:
        obj (Any): Target object or container.

    Returns:
        Any: JSON-safe serializable object.
    """
    if obj is None or isinstance(obj, (int, float, bool, str)):
        return obj
    if isinstance(obj, (list, tuple, set)):
        return [json_serialize_safe(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): json_serialize_safe(v) for k, v in obj.items()}
    return str(obj)
