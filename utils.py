def clean_x_handle(handle) -> str | None:
    if not handle or not isinstance(handle, str):
        return None
    handle = handle.strip().rstrip("/")
    if "x.com" in handle or "twitter.com" in handle:
        if "://" in handle:
            handle = handle.split("://")[-1]
        parts = handle.split("/")
        if len(parts) > 1 and parts[-1]:
            handle = parts[-1].split("?")[0]
        else:
            return None
    if not handle:
        return None
    if not handle.startswith("@"):
        handle = f"@{handle}"
    return handle if handle != "@" else None
