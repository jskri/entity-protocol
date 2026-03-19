"""
Parser for the request protocol.

Grammar
-------
    Request   := Command Path Body?
    Command   := "CREATE" | "ALTER" | "DELETE" | "WATCH" | "READ"
    Path      := ("/" Word)+
    Body      := "{" (KeyValue ("," KeyValue)*)? "}"
    KeyValue  := Word ":" (Word | Path)
    Word      := [a-zA-Z0-9_-]+

Note: values of the "from" and "to" keys are parsed as Timestamp rather
than Word.
    Timestamp := [a-zA-Z0-9_:+-]+
"""

import re
from dataclasses import dataclass, field

COMMANDS: frozenset[str] = frozenset({"CREATE", "ALTER", "DELETE", "WATCH", "READ"})

_WORD_PAT = re.compile(r"[a-zA-Z0-9_-]+")
_TIMESTAMP_PAT = re.compile(r"[a-zA-Z0-9_:+\-]+")
_TIMESTAMP_KEYS: frozenset[str] = frozenset({"from", "to"})


@dataclass
class ParseError(Exception):
    message: str
    command: str = ""
    path: str = ""


@dataclass
class Request:
    command: str
    path: str
    body: dict[str, str] = field(default_factory=dict)


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    # ------------------------------------------------------------------
    # Primitives
    # ------------------------------------------------------------------

    def _skip(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t\n":
            self.pos += 1

    def _peek(self) -> str:
        self._skip()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _expect(self, ch: str) -> None:
        self._skip()
        if self.pos >= len(self.text) or self.text[self.pos] != ch:
            raise ParseError(message=f"Expected {ch!r} at position {self.pos}")
        self.pos += 1

    def _word(self) -> str:
        self._skip()
        m = _WORD_PAT.match(self.text, self.pos)
        if not m:
            raise ParseError(message=f"Expected word at position {self.pos}")
        self.pos = m.end()
        return m.group()

    def _timestamp(self) -> str:
        self._skip()
        m = _TIMESTAMP_PAT.match(self.text, self.pos)
        if not m:
            raise ParseError(message=f"Expected timestamp at position {self.pos}")
        self.pos = m.end()
        return m.group()

    def _path(self) -> str:
        self._skip()
        if self.pos >= len(self.text) or self.text[self.pos] != "/":
            raise ParseError(message=f"Expected '/' at position {self.pos}")
        segments: list[str] = []
        while self.pos < len(self.text) and self.text[self.pos] == "/":
            self.pos += 1
            m = _WORD_PAT.match(self.text, self.pos)
            if not m:
                raise ParseError(
                    message=f"Expected word after '/' at position {self.pos}"
                )
            segments.append(m.group())
            self.pos = m.end()
        return "/" + "/".join(segments)

    # ------------------------------------------------------------------
    # Grammar rules
    # ------------------------------------------------------------------

    def _parse_command(self) -> str:
        w = self._word()
        if w not in COMMANDS:
            raise ParseError(message=f"Unknown command: {w!r}")
        return w

    def _parse_value(self, key: str) -> str:
        if key in _TIMESTAMP_KEYS:
            return self._timestamp()
        if self._peek() == "/":
            return self._path()
        return self._word()

    def _parse_body(self) -> dict[str, str]:
        self._skip()
        if self.pos >= len(self.text) or self.text[self.pos] != "{":
            return {}
        self.pos += 1  # consume '{'
        result: dict[str, str] = {}
        if self._peek() == "}":
            self.pos += 1
            return result
        while True:
            key = self._word()
            self._expect(":")
            result[key] = self._parse_value(key)
            self._skip()
            if self._peek() == ",":
                self.pos += 1
            elif self._peek() == "}":
                self.pos += 1
                break
            else:
                raise ParseError(message=f"Expected ',' or '}}' at position {self.pos}")
        return result

    def parse(self) -> Request:
        command = ""
        path = ""
        try:
            command = self._parse_command()
            path = self._path()
            body = self._parse_body()
            self._skip()
            if self.pos < len(self.text):
                raise ParseError(
                    message=f"Unexpected content: {self.text[self.pos :]!r}",
                    command=command,
                    path=path,
                )
            return Request(command=command, path=path, body=body)
        except ParseError as exc:
            raise ParseError(
                message=exc.message,
                command=exc.command or command,
                path=exc.path or path,
            ) from exc


def parse(text: str) -> Request:
    return _Parser(text.strip()).parse()
