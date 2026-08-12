from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class JsonStore:
    def __init__(self, root: Path, data_directory: Path | None = None) -> None:
        self.root = root
        self.data = data_directory or root / "data"

    def read_models(self, filename: str, model: type[T]) -> list[T]:
        path = self.data / filename
        if not path.exists():
            return []
        content = json.loads(path.read_text(encoding="utf-8"))
        items = content.get("items", content) if isinstance(content, dict) else content
        if not isinstance(items, list):
            raise ValueError(f"{path} must contain a JSON list or an items list")
        return [model.model_validate(item) for item in items]

    def read(self, filename: str, default: Any) -> Any:
        path = self.data / filename
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, filename: str, value: Any) -> bool:
        path = self.data / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        serialisable: Any
        if isinstance(value, BaseModel):
            serialisable = value.model_dump(mode="json")
        elif isinstance(value, list):
            serialisable = [
                item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for item in value
            ]
        else:
            serialisable = value
        rendered = json.dumps(serialisable, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") == rendered:
            return False
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
        return True
