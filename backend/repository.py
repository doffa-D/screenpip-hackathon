"""Small single-process JSON store; recordings and desktop logs stay local."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path


class Repository:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.recovery_warnings = []

    def read_recoverable(self, name, default, validate=None):
        """Only derived indexes use this; retain damaged bytes for recovery."""
        try:
            data = self.read(name, default)
            if validate:
                validate(data)
            return data
        except (ValueError, UnicodeDecodeError, TypeError, KeyError, AttributeError):
            path = self.directory / f'{name}.json'
            suffix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            quarantine = path.with_suffix(f'.corrupt-{suffix}.json')
            path.replace(quarantine)
            self.recovery_warnings.append(f'{name} was damaged. The original file was preserved as {quarantine.name}; verified discovery records will rebuild available memories.')
            return default

    def read(self, name, default):
        path = self.directory / f'{name}.json'
        if not path.exists():
            return default
        # Surface corrupted storage instead of silently replacing saved history.
        return json.loads(path.read_text(encoding='utf-8'))

    def write(self, name, data):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f'{name}.json'
        temporary = path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
