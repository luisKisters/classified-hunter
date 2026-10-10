import argparse
from pathlib import Path

from . import pipeline
from .fetch import Fetch, FetchError
from .profile import ProfileError, load
from .store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description="kleinscoutr listing hunt pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "lists", "prefilter", "details", "score", "verify", "report", "status"):
        command = commands.add_parser(name)
        command.add_argument("--profile", default="profiles/bike.json")
        if name in ("run", "lists"):
            command.add_argument(
                "--fresh", action="store_true", help="short list cache TTL (~1 hour)"
            )
        if name in ("run", "details"):
            command.add_argument(
                "--all",
                action="store_true",
                dest="all_tiers",
                help="fetch details from all title tiers",
            )
        if name in ("run", "verify", "report"):
            command.add_argument("--top", type=int, help="number of top candidates")
    args = parser.parse_args(argv)
    if getattr(args, "top", None) is not None and args.top < 0:
        parser.error("--top must be nonnegative")
    try:
        profile = load(args.profile)
    except ProfileError as e:
        parser.error(str(e))
    store = Store(Path("runs") / profile["name"] / f"{profile['name']}.db")
    try:
        if args.command == "status":
            for status, count in store.counts().items():
                print(f"{status}: {count}")
            return
        fetch = Fetch(store.root / "cache", store.log)
        kwargs = {k: v for k, v in vars(args).items() if k not in ("command", "profile")}
        getattr(pipeline, args.command)(
            profile, store, fetch, pipeline.source_for(profile), **kwargs
        )
    except FetchError as e:
        parser.exit(1, f"{e}\n")
    finally:
        store.close()
