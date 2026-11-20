"""Annual, deterministic civilization simulation."""

from .rules import LEGACY

# Kept for callers that inspect the default model. A particular run uses Rules.version.
MODEL_VERSION = LEGACY.version

