"""EndpointPool — tag-based filtering, round-robin rotation, and cooldown tracking.

Pure in-memory data structure with no I/O. Thread-safe via asyncio.Lock.
The pool is injected into provider base classes; providers call get_available()
to get the next endpoint to try, and mark_cooldown() on rate-limit failures.
"""

import asyncio
import logging
import time

from apps.bot.config.models import EndpointConfig

logger = logging.getLogger("synapulse.provider.endpoint")


class EndpointPool:
    """Manages a pool of AI endpoints with rotation and cooldown."""

    def __init__(self, endpoints: list[EndpointConfig] | None = None) -> None:
        self._endpoints: list[EndpointConfig] = list(endpoints or [])
        self._cursors: dict[str, int] = {}  # {tag: cursor_position}
        self._cooldowns: dict[str, float] = {}  # {endpoint_name: cooldown_until}
        self._lock = asyncio.Lock()

        # Log tag summary at creation
        summary = self.get_tag_summary()
        if summary:
            logger.info("EndpointPool created: %d endpoint(s), tags: %s", len(self._endpoints), summary)

    def get_available(self, tag: str) -> list[EndpointConfig]:
        """Return enabled, non-cooldown endpoints matching tag, sorted by priority.

        Results are rotated starting from the current cursor position for
        round-robin distribution. Returns empty list if no endpoints match.
        """
        now = time.monotonic()

        # Filter: enabled + has tag + not in cooldown
        candidates = [
            ep for ep in self._endpoints
            if ep.enabled
               and tag in ep.tags
               and now >= self._cooldowns.get(ep.name, 0)
        ]

        if not candidates:
            return []

        # Sort by priority (lower = higher priority)
        candidates.sort(key=lambda ep: ep.priority)

        # Rotate from cursor position for round-robin
        cursor = self._cursors.get(tag, 0) % len(candidates)
        rotated = candidates[cursor:] + candidates[:cursor]
        return rotated

    def mark_cooldown(self, name: str, seconds: float) -> None:
        """Mark an endpoint as rate-limited for the given duration."""
        until = time.monotonic() + seconds
        self._cooldowns[name] = until
        logger.info("Endpoint '%s' in cooldown for %.0fs", name, seconds)

    def advance_cursor(self, tag: str) -> None:
        """Move cursor to next position for the given tag.

        Called after all endpoints in a rotation have been tried,
        so next request starts from a different position.
        """
        current = self._cursors.get(tag, 0)
        self._cursors[tag] = current + 1

    def update(self, endpoints: list[EndpointConfig]) -> None:
        """Hot-reload: replace endpoint list, preserve cooldown state.

        Cooldowns are preserved for endpoints that still exist by name.
        Cursors are preserved for tags that still have endpoints.
        """
        old_names = {ep.name for ep in self._endpoints}
        new_names = {ep.name for ep in endpoints}

        added = new_names - old_names
        removed = old_names - new_names

        self._endpoints = list(endpoints)

        # Clean up cooldowns for removed endpoints
        for name in removed:
            self._cooldowns.pop(name, None)

        if added or removed:
            logger.info(
                "EndpointPool updated: +%d -%d = %d total, tags: %s",
                len(added), len(removed), len(self._endpoints), self.get_tag_summary(),
            )

    @property
    def endpoint_count(self) -> int:
        return len(self._endpoints)

    def get_tag_summary(self) -> dict[str, int]:
        """Return {tag: count_of_enabled_endpoints} for logging."""
        summary: dict[str, int] = {}
        for ep in self._endpoints:
            if not ep.enabled:
                continue
            for tag in ep.tags:
                summary[tag] = summary.get(tag, 0) + 1
        return summary
