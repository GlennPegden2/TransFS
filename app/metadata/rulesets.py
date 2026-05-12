"""Ruleset loading for metadata parsing."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any

import yaml


@dataclass
class Ruleset:
    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    tokens: Optional[dict] = None
    rules: Optional[list] = None


class RulesetRegistry:
    """Load and cache rulesets from config/metadata/rulesets."""

    def __init__(self, config_dir: str = "config") -> None:
        self.config_dir = config_dir
        self._cache: Dict[str, Ruleset] = {}

    def _ruleset_dir(self) -> str:
        return os.path.join(self.config_dir, "metadata", "rulesets")

    def load(self, name: str) -> Optional[Ruleset]:
        if name in self._cache:
            return self._cache[name]

        ruleset_path = os.path.join(self._ruleset_dir(), f"{name.lower()}.yaml")
        if not os.path.exists(ruleset_path):
            return None

        with open(ruleset_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        ruleset = Ruleset(
            name=data.get("name", name),
            version=data.get("version"),
            description=data.get("description"),
            tokens=data.get("tokens"),
            rules=data.get("rules"),
        )
        self._cache[name] = ruleset
        return ruleset

    def load_all(self) -> Dict[str, Ruleset]:
        ruleset_dir = self._ruleset_dir()
        if not os.path.isdir(ruleset_dir):
            return {}

        for filename in os.listdir(ruleset_dir):
            if not filename.lower().endswith(".yaml"):
                continue
            name = filename[:-5]
            self.load(name)
        return dict(self._cache)


def load_ruleset(name: str, config_dir: str = "config") -> Optional[Ruleset]:
    return RulesetRegistry(config_dir=config_dir).load(name)
