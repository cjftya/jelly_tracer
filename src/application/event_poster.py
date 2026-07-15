from collections import defaultdict
from typing import Any, Callable, DefaultDict, Optional


class EventPoster:
    """Publish named events to handlers registered by the application layer."""

    LOG = "log"

    def __init__(self):
        self._handlers: DefaultDict[str, list[Callable[..., None]]] = defaultdict(list)
        self._log_handler: Optional[Callable[..., None]] = None

    def set_log_handler(self, handler: Optional[Callable[..., None]]) -> None:
        if self._log_handler:
            self.unsubscribe(self.LOG, self._log_handler)
        self._log_handler = handler
        if handler:
            self.subscribe(self.LOG, handler)

    def subscribe(self, event_name: str, handler: Callable[..., None]) -> None:
        if handler not in self._handlers[event_name]:
            self._handlers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: Callable[..., None]) -> None:
        handlers = self._handlers.get(event_name, [])
        if handler in handlers:
            handlers.remove(handler)

    def post(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        for handler in tuple(self._handlers.get(event_name, [])):
            handler(*args, **kwargs)

    def log(self, message: str, is_system: bool = False) -> None:
        self.post(self.LOG, message, is_system)