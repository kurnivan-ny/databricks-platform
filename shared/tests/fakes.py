"""Tiny in-memory stand-in for a SparkSession, enough to unit-test SQL orchestration.

It records every SQL statement and answers COUNT/DISTINCT queries from configurable
dictionaries; it does not execute SQL.
"""

from __future__ import annotations


class FakeResult:
    def __init__(self, spark: FakeSpark, rows: list[tuple]):
        self._spark, self._rows = spark, rows

    def collect(self) -> list[tuple]:
        return self._rows

    def createOrReplaceTempView(self, name: str) -> None:
        self._spark.temp_views.append(name)


class FakeFrame(FakeResult):
    def __init__(self, spark: FakeSpark):
        super().__init__(spark, [])

    def format(self, fmt):
        self._spark.reads.append(("format", fmt))
        return self

    def schema(self, ddl):
        self._spark.reads.append(("schema", ddl))
        return self

    def load(self, paths):
        self._spark.reads.append(("load", paths))
        return self

    def selectExpr(self, *exprs):
        self._spark.reads.append(("selectExpr", exprs))
        return self


class FakeCatalog:
    def __init__(self, existing: set[str]):
        self.existing = existing

    def tableExists(self, name: str) -> bool:
        return name in self.existing


class FakeSpark:
    def __init__(self, existing=(), counts=None, loaded_files=(), default_count=10):
        self.statements: list[str] = []
        self.temp_views: list[str] = []
        self.reads: list[tuple] = []
        self.catalog = FakeCatalog(set(existing))
        self.counts = counts or {}  # substring of the SQL -> COUNT(*) answer
        self.loaded_files = list(loaded_files)
        self.default_count = default_count

    @property
    def read(self) -> FakeFrame:
        return FakeFrame(self)

    def sql(self, statement: str) -> FakeResult:
        self.statements.append(statement)
        if statement.startswith("SELECT DISTINCT _source_file"):
            return FakeResult(self, [(f"dbfs:/Volumes/x/{f}",) for f in self.loaded_files])
        if statement.startswith("SELECT COUNT(*)"):
            for fragment, value in self.counts.items():
                if fragment in statement:
                    return FakeResult(self, [(value,)])
            violation = "WHERE NOT COALESCE" in statement
            return FakeResult(self, [(0 if violation else self.default_count,)])
        return FakeResult(self, [])

    def executed(self, prefix: str) -> list[str]:
        return [s for s in self.statements if s.startswith(prefix)]
