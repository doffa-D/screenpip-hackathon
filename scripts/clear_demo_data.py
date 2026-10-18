"""Remove only explicitly marked seeded objects; run while Melon is closed."""
import argparse
import json
from backend.config import Settings
from backend.repository import Repository
from .seed_demo_data import guard_offline, is_demo, STORES


def clear(repository):
    removed = {}
    for name in (*STORES, 'tasks', 'schedule_occurrences'):
        records = repository.read(name, {})
        retained = {key: value for key, value in records.items() if not is_demo(key, value)}
        removed[name] = len(records) - len(retained)
        if removed[name]:
            repository.write(name, retained)
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default=None)
    args = parser.parse_args()
    guard_offline()
    print(json.dumps(clear(Repository(args.data_dir or Settings().data_dir)), indent=2))


if __name__ == '__main__':
    main()
