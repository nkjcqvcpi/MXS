"""Command-specific response validation."""

from dataclasses import dataclass

from .errors import ReplyMismatchError
from .models import Ack, Pong, Reply


@dataclass(frozen=True, slots=True)
class ResponseExpectation:
    response_class: type[Ack] | type[Pong] | type[Reply]
    reply_class: type[Reply] | None = None
    content_id: int | None = None
    info: int | None = None
    element_count: int | None = None
    element_size: int | None = None

    def validate(self, response: Ack | Pong | Reply) -> None:
        if not isinstance(response, self.response_class):
            raise ReplyMismatchError(
                f"expected {self.response_class.__name__}, received {type(response).__name__}"
            )
        if not isinstance(response, Reply):
            return
        checks = (
            (self.reply_class, type(response), "reply class"),
            (self.content_id, response.content_id, "content ID"),
            (self.info, response.info, "info"),
            (self.element_count, response.element_count, "element count"),
            (self.element_size, response.element_size, "element size"),
        )
        for expected, actual, label in checks:
            if expected is not None and actual != expected:
                raise ReplyMismatchError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


ACK = ResponseExpectation(Ack)
PONG = ResponseExpectation(Pong)


def reply(
    reply_class: type[Reply],
    content_id: int,
    *,
    info: int = 0,
    element_count: int | None = None,
) -> ResponseExpectation:
    return ResponseExpectation(
        Reply,
        reply_class=reply_class,
        content_id=content_id,
        info=info,
        element_count=element_count,
    )
