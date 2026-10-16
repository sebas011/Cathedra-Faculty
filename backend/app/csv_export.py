import csv
from collections.abc import Iterable
from io import StringIO


def safe_cell(value: object) -> object:
    if isinstance(value, str) and value.lstrip("\ufeff\t\r\n ").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class SafeCsvWriter:
    def __init__(self, output: StringIO) -> None:
        self.writer = csv.writer(output)

    def writerow(self, row: Iterable[object]) -> None:
        self.writer.writerow([safe_cell(value) for value in row])

    def writerows(self, rows: Iterable[Iterable[object]]) -> None:
        for row in rows:
            self.writerow(row)
