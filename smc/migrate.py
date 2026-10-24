"""Dry-run by default. --apply creates only a NEW CHOCH ledger; never migrates production."""
import argparse
import json
from .notification_repository import initialize, DEFAULT_PATH


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(initialize(args.path, args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
