"""Publish a finished experiment file from staging on the same filesystem."""
import os


def publish_file(staged, destination):
    """Install the completed file only if this process wins the destination name."""
    if os.name == "nt":
        os.rename(staged, destination)  # Windows refuses an existing destination.
    else:
        os.link(staged, destination)  # POSIX rename would replace an existing file.
