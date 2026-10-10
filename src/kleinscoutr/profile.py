import json
import re
from pathlib import Path


class ProfileError(ValueError):
    pass


def validate(profile):
    def check(value, kind, key):
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            raise ProfileError(f"{key}: expected {kind.__name__}")

    def patterns(value, key, capture=False):
        check(value, list, key)
        for i, pattern in enumerate(value):
            check(pattern, str, f"{key}[{i}]")
            try:
                compiled = re.compile(pattern, re.I)
            except re.error as e:
                raise ProfileError(f"{key}[{i}]: invalid regex: {e}") from e
            if capture and compiled.groups < 1:
                raise ProfileError(f"{key}[{i}]: needs a capture group")

    def pair(value, key):
        check(value, list, key)
        if len(value) != 2:
            raise ProfileError(f"{key}: expected [min, max]")
        for n in value:
            check(n, int, key)
        if value[0] > value[1]:
            raise ProfileError(f"{key}: min exceeds max")

    check(profile, dict, "profile")
    for key, kind in [
        ("name", str),
        ("site", str),
        ("location", str),
        ("radius", int),
        ("price", list),
        ("searches", list),
    ]:
        if key not in profile:
            raise ProfileError(f"{key}: required")
        check(profile[key], kind, key)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile["name"]):
        raise ProfileError("name: use letters, digits, underscore or hyphen")
    if profile["site"] != "kleinanzeigen":
        raise ProfileError("site: expected kleinanzeigen")
    pair(profile["price"], "price")
    for i, search in enumerate(profile["searches"]):
        key = f"searches[{i}]"
        check(search, dict, key)
        if search.get("kind") not in ("keyword", "category"):
            raise ProfileError(f"{key}.kind: expected keyword or category")
        field, kind = ("q", str) if search["kind"] == "keyword" else ("category_id", int)
        check(search.get(field), kind, f"{key}.{field}")
    for key, default in [
        ("max_pages", 25),
        ("image_rule", "$_59.JPG"),
        ("report_top", 20),
        ("verify_top", 20),
        ("detail_title_patterns", []),
        ("keep_patterns", []),
    ]:
        profile.setdefault(key, default)
        check(profile[key], type(default), key)
        if isinstance(default, int) and profile[key] < 0:
            raise ProfileError(f"{key}: must be nonnegative")
    for key in ("detail_title_patterns", "keep_patterns"):
        patterns(profile[key], key)
    for block, fields in [("kills", ("title", "text")), ("awards", ("text", "seller_badges"))]:
        check(profile.get(block, []), list, block)
        for i, rule in enumerate(profile.get(block, [])):
            key = f"{block}[{i}]"
            check(rule, dict, key)
            check(rule.get("id"), str, f"{key}.id")
            if rule.get("field") not in fields:
                raise ProfileError(f"{key}.field: expected {fields}")
            patterns(rule.get("patterns"), f"{key}.patterns")
            if block == "awards":
                check(rule.get("points"), int, f"{key}.points")
                patterns(rule.get("requires_patterns", []), f"{key}.requires_patterns")
    blocks = {
        "size": ["min", "max", "points"],
        "defects": ["penalty_per_distinct", "penalty_cap"],
        "condition": ["min_distinct", "points"],
        "photos": ["threshold", "points"],
        "seller": [
            "ads_threshold",
            "ads_penalty",
            "min_age_years",
            "age_points",
            "min_badges",
            "badges_points",
            "fresh_account_penalty",
        ],
    }
    for block, numbers in blocks.items():
        cfg = profile.get(block, {})
        check(cfg, dict, block)
        for key in numbers:
            if key in cfg:
                check(cfg[key], int, f"{block}.{key}")
        if block in ("size", "defects", "condition"):
            patterns(cfg.get("patterns", []), f"{block}.patterns", capture=block == "size")
    cfg = profile.get("size", {})
    if "recognition_range" in cfg:
        pair(cfg["recognition_range"], "size.recognition_range")
    for key in ("labels", "labels_kill"):
        check(cfg.get(key, []), list, f"size.{key}")
        for value in cfg.get(key, []):
            check(value, str, f"size.{key}")
    return profile


def load(path, local_path=None):
    path = Path(path)
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
        local = Path(local_path) if local_path is not None else Path("profiles/local.json")
        if local.exists() and local.resolve() != path.resolve():
            override = json.loads(local.read_text(encoding="utf-8"))
            if not isinstance(override, dict):
                raise ProfileError("local: expected object")
            if not isinstance(profile, dict):
                raise ProfileError("profile: expected object")
            profile.update(override)
        return validate(profile)
    except (OSError, json.JSONDecodeError) as e:
        raise ProfileError(f"{path}: {e}") from e
