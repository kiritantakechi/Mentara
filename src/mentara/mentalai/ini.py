"""Read Westwood INI data the way the game engine does.

Section and key names compare without case, a repeated section merges
into the first, and a repeated key keeps its last value: Ares replaces
the INI parser (0x5260D9) so that a later copy of a key wins. Mental
Omega's rules repeat no key with different values, so its data reads the
same either way.
"""

from dataclasses import dataclass
from typing import Final
lazy from collections.abc import Mapping

__all__ = ["IniData", "parse_number", "split_list"]

_COMMENT: Final[str] = ";"
# A flag is on when its value starts with one of these (yes, true, 1).
_ON: Final[frozenset[str]] = frozenset("yt1")


@dataclass(frozen=True, slots=True)
class IniData:
    """Sections of an INI file, keyed by lower-case name.

    Attributes:
        sections: Lower-case section name to its keys (lower-case key to
            value).
        names: Lower-case section name to its first spelling.
        key_orders: Lower-case section name to its keys' first
            spellings,
            in file order.
    """

    sections: Mapping[str, Mapping[str, str]]
    names: Mapping[str, str]
    key_orders: Mapping[str, tuple[str, ...]]

    @classmethod
    def parse(cls, text: str) -> IniData:
        """Parse INI text.

        Args:
            text: The file's text.

        Returns:
            The parsed sections.
        """
        sections: dict[str, dict[str, str]] = {}
        names: dict[str, str] = {}
        orders: dict[str, list[str]] = {}
        current: str | None = None
        for raw in text.splitlines():
            line = raw.split(_COMMENT, 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and "]" in line:
                name = line[1 : line.index("]")].strip()
                current = name.lower()
                names.setdefault(current, name)
                sections.setdefault(current, {})
                orders.setdefault(current, [])
                continue
            if current is None or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            folded = key.lower()
            if folded not in sections[current]:
                orders[current].append(key)
            sections[current][folded] = value.strip()
        return cls(
            sections=sections,
            names=names,
            key_orders={name: tuple(keys) for name, keys in orders.items()},
        )

    def has(self, section: str) -> bool:
        """Whether the file has a section of this name.

        Args:
            section: Section name, any case.

        Returns:
            True if the section exists.
        """
        return section.lower() in self.sections

    def get(self, section: str, key: str) -> str | None:
        """The value of a key, or None if the section or key is absent.

        Args:
            section: Section name, any case.
            key: Key name, any case.

        Returns:
            The value, or None.
        """
        keys = self.sections.get(section.lower())
        return None if keys is None else keys.get(key.lower())

    def flag(self, section: str, key: str, *, default: bool = False) -> bool:
        """A yes-or-no key, as the engine reads one.

        Args:
            section: Section name, any case.
            key: Key name, any case.
            default: The answer when the key is absent or empty.

        Returns:
            True when the value starts with `y`, `t` or `1`.
        """
        value = self.get(section, key)
        if value is None or value == "":
            return default
        return value[0].lower() in _ON

    def number(self, section: str, key: str, default: float = 0.0) -> float:
        """A numeric key; a trailing percent sign is dropped.

        Args:
            section: Section name, any case.
            key: Key name, any case.
            default: The number when the key is absent or not one.

        Returns:
            The value as a float.
        """
        return parse_number(self.get(section, key), default)

    def integer(self, section: str, key: str, default: int = 0) -> int:
        """A numeric key, truncated to an integer.

        Args:
            section: Section name, any case.
            key: Key name, any case.
            default: The number when the key is absent or not one.

        Returns:
            The value as an int.
        """
        return int(self.number(section, key, float(default)))

    def token(self, section: str, key: str, default: str = "") -> str:
        """A keyword key, lower-cased for comparison.

        Args:
            section: Section name, any case.
            key: Key name, any case.
            default: The keyword when the key is absent or empty.

        Returns:
            The value in lower case.
        """
        return (self.get(section, key) or default).lower()

    def listed(self, section: str, key: str) -> tuple[str, ...]:
        """The items of a comma-separated key.

        Args:
            section: Section name, any case.
            key: Key name, any case.

        Returns:
            The stripped, non-empty items; none when the key is absent.
        """
        return split_list(self.get(section, key))

    def name(self, section: str) -> str:
        """A section's own spelling, or the name given if it has none.

        Args:
            section: Section name, any case.

        Returns:
            The spelling the file uses.
        """
        return self.names.get(section.lower(), section)

    def keys(self, section: str) -> tuple[str, ...]:
        """A section's keys in file order, as first spelled.

        Args:
            section: Section name, any case.

        Returns:
            Its keys, or an empty tuple.
        """
        return self.key_orders.get(section.lower(), ())

    def type_list(self, section: str) -> tuple[str, ...]:
        """The values of a registry section, without repeats.

        The engine registers a type the first time a registry lists it,
        so a repeated name keeps its first place.

        Args:
            section: Registry section such as `InfantryTypes`.

        Returns:
            The listed names in registration order.
        """
        seen: set[str] = set()
        listed: list[str] = []
        for key in self.keys(section):
            value = self.get(section, key)
            if value is None or not value.strip() or value.lower() in seen:
                continue
            seen.add(value.lower())
            listed.append(value)
        return tuple(listed)


def parse_number(value: str | None, default: float = 0.0) -> float:
    """Read an INI value as a number.

    Args:
        value: The raw value, or None.
        default: The number for a missing or malformed value.

    Returns:
        The value as a float, a trailing percent sign dropped.
    """
    if value is None:
        return default
    try:
        return float(value.strip().rstrip("%"))
    except ValueError:
        return default


def split_list(value: str | None) -> tuple[str, ...]:
    """Split a comma-separated INI value into its non-empty items.

    Args:
        value: The raw value, or None.

    Returns:
        The stripped items.
    """
    if value is None:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())
