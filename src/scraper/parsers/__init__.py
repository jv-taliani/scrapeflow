from scraper.parsers.base import Parser, ParseResult

_REGISTRY: dict[str, Parser] = {}


def register(cls: type[Parser]) -> type[Parser]:
    _REGISTRY[cls.source] = cls()
    return cls


def get_parser(source: str) -> Parser:
    try:
        return _REGISTRY[source]
    except KeyError:
        raise KeyError(f"fonte desconhecida: {source!r}") from None


def sources() -> list[str]:
    return sorted(_REGISTRY)


from scraper.parsers import books  # noqa: E402

__all__ = ["ParseResult", "Parser", "books", "get_parser", "register", "sources"]
