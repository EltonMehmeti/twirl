from dataclasses import dataclass

from twirl.models import ActorKind


@dataclass(frozen=True)
class Actor:
    kind: ActorKind
    id: int | None = None


SYSTEM = Actor(ActorKind.SYSTEM)
