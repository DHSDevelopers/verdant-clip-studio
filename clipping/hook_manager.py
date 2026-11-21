"""Custom hook source handling (local path or Google Drive)."""

import os


def download_custom_hook(cfg, output_dir=None):
    source = getattr(cfg, "hook_source", None)
    if not source:
        return None
    if os.path.exists(source):
        return os.path.abspath(source)

    if "drive.google.com" in str(source):
        from .engine import _download_gdrive

        target = os.path.join(
            output_dir or cfg.outputs_dir, "custom_hook_source.mp4"
        )
        _download_gdrive(source, target)
        if os.path.exists(target):
            return target
    raise RuntimeError(f"Custom hook source could not be resolved: {source}")
