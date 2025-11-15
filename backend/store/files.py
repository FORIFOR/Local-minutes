import os


def artifact_dir() -> str:
    p = os.path.join("backend", "artifacts")
    os.makedirs(p, exist_ok=True)
    return p


def artifact_path_for_event(event_id: str, name: str) -> str:
    d = os.path.join(artifact_dir(), event_id)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)

