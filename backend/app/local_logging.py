import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class PrivateDiagnosticFormatter(logging.Formatter):
    def format(self, record):
        if record.name == "cathedra.performance":
            return super().format(record)
        failure = record.exc_info[0].__name__ if record.exc_info else "service_event"
        return f"{self.formatTime(record)} {record.levelname} {record.name} {failure}"


def configure_local_logging(data_directory: Path):
    directory = data_directory / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "service.log", maxBytes=1_048_576, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        PrivateDiagnosticFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    return handler
