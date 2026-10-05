"""Runbook retrieval. Runbooks are markdown with YAML front-matter (category, actions, dangerous)."""
from pathlib import Path

import yaml


def load_runbooks(directory):
    out = []
    for p in sorted(Path(directory).glob("*.md")):
        _, fm, body = p.read_text().split("---", 2)
        out.append(dict(yaml.safe_load(fm), body=body.strip(), source=p.name))
    return out


def retrieve(runbooks, category):
    return [r for r in runbooks if r["category"] == category]
