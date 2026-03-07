from typing import Any, Dict


def get_email_context() -> Dict[str, Any]:
    """
    Returns the centralized context payload for Jinja2 email templates.
    """
    return {
        "bg_color": "#f6f9fc",
        "card_bg": "#ffffff",
        "text_color": "#525f7f",
        "primary_color": "#3b82f6",
        "secondary_color": "#8898aa",
        "heading_color": "#32325d",
        "divider_color": "#f0f0f0",
        "footer_text_color": "#8898aa",
        "container_radius": "8px",
        "container_shadow": "0 4px 6px rgba(0, 0, 0, 0.05)",
        "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    }
