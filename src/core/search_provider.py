from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, List, Optional

@dataclass
class FilterField:
    name: str
    label: str
    values: List[str] = field(default_factory=list)

@dataclass
class SearchQuery:
    text: str = ""
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    time_from: Optional[time] = None
    time_to: Optional[time] = None
    types: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    severity: Optional[str] = None
    module: Optional[str] = None
    regex_enabled: bool = False

@dataclass
class SearchResult:
    timestamp: datetime
    source: str
    type: str
    summary: str
    detail: Any
    relevance: float

class SearchProvider(ABC):
    # Set this in each subclass so SearchEngine can filter by module
    module_name: str = ""

    @abstractmethod
    def search(self, query: SearchQuery) -> List[SearchResult]:
        ...

    @abstractmethod
    def get_filterable_fields(self) -> List[FilterField]:
        ...
