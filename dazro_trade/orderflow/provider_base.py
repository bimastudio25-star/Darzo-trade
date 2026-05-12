from __future__ import annotations

from abc import ABC, abstractmethod


class OrderflowProvider(ABC):
    confidence_level = "LOW"

    @abstractmethod
    def snapshot(self, symbol: str) -> dict:
        raise NotImplementedError
