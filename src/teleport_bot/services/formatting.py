from html import escape


def escape_html(value: object | None) -> str:
    """Render untrusted values safely under the bot's global HTML parse mode."""
    return escape("" if value is None else str(value), quote=True)
