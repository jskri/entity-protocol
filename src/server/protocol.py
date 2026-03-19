"""Response formatting."""


def format_response(status: int, body: dict[str, str]) -> str:
    if not body:
        return f"{status} {{}}"
    parts = ", ".join(f"{k}: {v}" for k, v in body.items())
    return f"{status} {{ {parts} }}"
