def notification(label, text):
    return f"[{label}] permesso richiesto\n\n{text}"


def stop(label, summary):
    if summary and summary.strip():
        return f"[{label}] finito\n\n{summary.strip()}"
    return f"[{label}] finito"
