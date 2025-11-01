from dataclasses import dataclass, asdict


@dataclass
class PatternItem:
    pattern: str
    replace: str = ""
    case_sensitive: bool = True,
    name: str | None = None,
    enabled: bool = True

    def to_json(self):
        return asdict(self)

    @classmethod
    def from_json(cls, d):
        return cls(d.get("pattern", ""), d.get("replace", ""), d.get("case_sensitive", True), d.get("name", None), d.get("enabled", True))
