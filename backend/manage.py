#!/usr/bin/env python
import os
import sys


def main() -> None:
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "queue_stats_backend.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "Couldn't import Django. Make sure it is installed and available on "
            "your PYTHONPATH environment variable, or activate a virtual "
            "environment where it is installed.",
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

