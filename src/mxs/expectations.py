"""Command-specific response validation."""

from dataclasses import dataclass

from .errors import ReplyMismatchError
from .models import Ack, Pong, Reply


@dataclass(frozen=True, slots=True)
class ResponseExpectation:
    response_class: type[Ack] | type[Pong] | type[Reply]
    reply_class: type[Reply] | None = None
    content_ids: frozenset[int] | None = None
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
            (self.info, response.info, "info"),
            (self.element_count, response.element_count, "element count"),
            (self.element_size, response.element_size, "element size"),
        )
        if self.content_ids is not None and response.content_id not in self.content_ids:
            raise ReplyMismatchError(
                f"content ID mismatch: expected one of {sorted(self.content_ids)!r}, "
                f"got {response.content_id!r}"
            )
        for expected, actual, label in checks:
            if expected is not None and actual != expected:
                raise ReplyMismatchError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


ACK = ResponseExpectation(Ack)
PONG = ResponseExpectation(Pong)


def reply(
    reply_class: type[Reply],
    content_id: int | None = None,
    *,
    content_ids: set[int] | frozenset[int] | None = None,
    info: int = 0,
    element_count: int | None = None,
    element_size: int | None = None,
) -> ResponseExpectation:
    if content_id is not None and content_ids is not None:
        raise ValueError("specify content_id or content_ids, not both")
    allowed = frozenset((content_id,)) if content_id is not None else None
    if content_ids is not None:
        allowed = frozenset(content_ids)
    if not allowed:
        raise ValueError("at least one reply content ID is required")
    if element_size is None:
        from .models import ByteReply, FloatReply, IntReply, StringReply, UserReply

        sizes: dict[type[Reply], int] = {
            ByteReply: 1,
            IntReply: 4,
            FloatReply: 4,
            StringReply: 1,
            UserReply: 1,
        }
        element_size = sizes.get(reply_class)
    return ResponseExpectation(
        Reply,
        reply_class=reply_class,
        content_ids=allowed,
        info=info,
        element_count=element_count,
        element_size=element_size,
    )
