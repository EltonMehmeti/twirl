from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request


class Database:
    def __init__(self, url: str) -> None:
        self.engine: Engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)
        self.sessionmaker = sessionmaker(self.engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.db.sessionmaker() as session:
        yield session
