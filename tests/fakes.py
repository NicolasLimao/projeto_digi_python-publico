from copy import deepcopy
from types import SimpleNamespace
from typing import Any


class FakeQuery:
    def __init__(self, client: "FakeSupabaseClient", table: str):
        self.client = client
        self.table = table
        self.operation = "select"
        self.payload: Any = None
        self.filters: list[tuple[str, str, Any]] = []
        self.ordering: tuple[str, bool] | None = None
        self.row_limit: int | None = None

    def insert(self, payload):
        self.operation, self.payload = "insert", payload
        return self

    def select(self, *_):
        self.operation = "select"
        return self

    def update(self, payload):
        self.operation, self.payload = "update", payload
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, key, value):
        self.filters.append((key, "eq", value))
        return self

    def gte(self, key, value):
        self.filters.append((key, "gte", value))
        return self

    def lt(self, key, value):
        self.filters.append((key, "lt", value))
        return self

    def lte(self, key, value):
        self.filters.append((key, "lte", value))
        return self

    def in_(self, key, values):
        self.filters.append((key, "in", list(values)))
        return self

    def order(self, key, desc=False):
        self.ordering = (key, desc)
        return self

    def limit(self, count):
        self.row_limit = count
        return self

    @staticmethod
    def _resolve(row, key):
        """Suporta o operador JSON do PostgREST (ex.: "metadata->>pergunta_norm")."""
        if "->>" in key:
            coluna, campo = key.split("->>", 1)
            valor = (row.get(coluna) or {}).get(campo)
            return None if valor is None else str(valor)
        return row.get(key)

    def _matches(self, row):
        for key, operation, value in self.filters:
            current = self._resolve(row, key)
            if operation == "eq" and current != value:
                return False
            if operation == "gte" and (current is None or current < value):
                return False
            if operation == "lt" and (current is None or current >= value):
                return False
            if operation == "lte" and (current is None or current > value):
                return False
            if operation == "in" and current not in value:
                return False
        return True

    def execute(self):
        rows = self.client.tables.setdefault(self.table, [])
        if self.operation == "insert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            inserted = []
            for payload in payloads:
                row = deepcopy(payload)
                row.setdefault("id", f"row-{self.client.next_id:06d}")
                self.client.next_id += 1
                rows.append(row)
                inserted.append(deepcopy(row))
            return SimpleNamespace(data=inserted)

        selected = [row for row in rows if self._matches(row)]
        if self.operation == "update":
            for row in selected:
                row.update(self.payload)
            return SimpleNamespace(data=deepcopy(selected))
        if self.operation == "delete":
            self.client.tables[self.table] = [row for row in rows if row not in selected]
            return SimpleNamespace(data=deepcopy(selected))
        if self.ordering:
            key, descending = self.ordering
            # Windows clocks can hand out identical timestamps to consecutive
            # inserts; break ties by insertion order (zero-padded ids) so the
            # fake stays deterministic like a real monotonic database would be.
            selected.sort(
                key=lambda row: (row.get(key) or "", row.get("id") or ""),
                reverse=descending,
            )
        if self.row_limit is not None:
            selected = selected[: self.row_limit]
        return SimpleNamespace(data=deepcopy(selected))


class FakeSupabaseClient:
    def __init__(self):
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.next_id = 1

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)
