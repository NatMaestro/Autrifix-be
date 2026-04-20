from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db.utils import ProgrammingError

from apps.jobs.models import ServiceCategory, ServiceRequest

TOKEN_RE = re.compile(r"[a-z0-9]+")
MODEL_DIR = Path(settings.BASE_DIR) / "var"
MODEL_PATH = MODEL_DIR / "issue_router_model.json"
_MODEL_LOCK = threading.Lock()
ML_CONFIDENCE_THRESHOLD = 0.58

# Rule-first high-signal intents. Keeps precision high for common roadside language.
RULES: dict[str, list[str]] = {
    "electrical": [
        "battery",
        "alternator",
        "starter",
        "no crank",
        "no start",
        "jump start",
        "wiring",
        "fuse",
        "dashboard light",
        "headlight",
    ],
    "engine": [
        "engine",
        "overheat",
        "smoke",
        "misfire",
        "stall",
        "stalling",
        "timing belt",
        "knocking",
        "rough idle",
        # Intentionally exclude generic "mechanic" to reduce collisions
        # with the "general mechanic" bucket.
    ],
    "tire": [
        "flat",
        "puncture",
        "blowout",
        "tire",
        "tyre",
        "wheel",
        "rim",
    ],
    "tow": [
        "tow",
        "towing",
        "accident",
        "collision",
        "crash",
        "stuck",
        "ditch",
    ],
    "brake": [
        "brake",
        "braking",
        "abs",
        "rotor",
        "pad",
    ],
}


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def _category_terms(category: ServiceCategory) -> set[str]:
    # Use `__dict__` to avoid triggering extra DB fetches for deferred fields,
    # and to stay safe if some optional columns haven't been migrated yet.
    slug = category.__dict__.get("slug", "")
    name = category.__dict__.get("name", "")
    description = category.__dict__.get("description", "")
    keywords = category.__dict__.get("keywords")

    terms = set(_tokenize(slug))
    terms.update(_tokenize(name))
    terms.update(_tokenize(description))
    if keywords:
        for raw in str(keywords).split(","):
            terms.update(_tokenize(raw.strip()))
    return terms


def _pick_fallback(categories: list[ServiceCategory]) -> ServiceCategory:
    general = next((c for c in categories if c.slug.lower() == "general-mechanic"), None)
    return general or categories[0]


def _load_model() -> dict[str, Any]:
    if not MODEL_PATH.exists():
        return {"classes": {}, "vocabulary": {}}
    with MODEL_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_model(model: dict[str, Any]) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with MODEL_PATH.open("w", encoding="utf-8") as f:
        json.dump(model, f)


def _ensure_category_lookup() -> tuple[dict[str, ServiceCategory], list[ServiceCategory]]:
    # Prefer active categories. For dev/MVP robustness, fall back to all categories
    # if none are marked active yet.
    def _load(active_only: bool) -> list[ServiceCategory]:
        base_qs = ServiceCategory.objects.all()
        if active_only:
            base_qs = base_qs.filter(is_active=True)

        try:
            # Attempt to load optional routing columns for better precision.
            return list(
                base_qs.only(
                    "id",
                    "slug",
                    "name",
                    "description",
                    "keywords",
                    "default_radius_km",
                    "priority",
                ).order_by("priority", "name"),
            )
        except ProgrammingError:
            # If optional columns aren't present in the DB yet, fall back to core fields.
            return list(base_qs.only("id", "slug", "name", "description").order_by("name"))

    categories = _load(active_only=True)
    if not categories:
        categories = _load(active_only=False)

    by_slug = {c.slug.lower(): c for c in categories}
    return by_slug, categories


def _rule_pick(issue_text: str, categories: list[ServiceCategory]) -> tuple[ServiceCategory | None, float, str]:
    text = (issue_text or "").lower()
    hits = defaultdict(int)
    for intent, patterns in RULES.items():
        for pattern in patterns:
            if pattern in text:
                hits[intent] += 1
    if not hits:
        return None, 0.0, "no_rule_hit"
    best_intent, score = max(hits.items(), key=lambda kv: kv[1])
    intent_tokens = {
        "electrical": ["electric", "battery", "starter", "alternator", "wiring"],
        "engine": ["engine", "smoke", "overheat", "misfire", "stall"],
        "tire": ["tire", "tyre", "wheel", "flat"],
        "tow": ["tow", "recovery", "accident"],
        "brake": ["brake"],
    }.get(best_intent, [best_intent])
    for c in categories:
        terms = _category_terms(c)
        if any(any(t in term for term in terms) for t in intent_tokens):
            confidence = min(0.95, 0.55 + 0.1 * score)
            return c, confidence, f"rule:{best_intent}"
    return None, 0.0, "rule_no_category_match"


def _ml_predict(issue_text: str, categories_by_slug: dict[str, ServiceCategory]) -> tuple[ServiceCategory | None, float, str]:
    tokens = _tokenize(issue_text)
    if not tokens:
        return None, 0.0, "ml_empty_text"
    with _MODEL_LOCK:
        model = _load_model()
    classes: dict[str, Any] = model.get("classes", {})
    if not classes:
        return None, 0.0, "ml_untrained"

    vocab_size = max(1, len(model.get("vocabulary", {})))
    total_docs = sum(int(v.get("doc_count", 0)) for v in classes.values()) or 1
    scored: list[tuple[float, str]] = []
    token_counts = Counter(tokens)
    for slug, stats in classes.items():
        doc_count = int(stats.get("doc_count", 0))
        token_total = int(stats.get("token_total", 0))
        token_map = stats.get("tokens", {})
        prior = math.log((doc_count + 1) / (total_docs + len(classes)))
        ll = prior
        for token, freq in token_counts.items():
            tok_ct = int(token_map.get(token, 0))
            prob = (tok_ct + 1) / (token_total + vocab_size)
            ll += freq * math.log(prob)
        scored.append((ll, slug))
    scored.sort(reverse=True)
    best_ll, best_slug = scored[0]
    runner_ll = scored[1][0] if len(scored) > 1 else best_ll - 2.0
    margin = best_ll - runner_ll
    confidence = max(0.4, min(0.93, 0.5 + margin / 5))
    category = categories_by_slug.get(best_slug)
    if not category:
        return None, 0.0, "ml_slug_missing"
    return category, confidence, "ml"


def route_issue(issue_text: str) -> dict[str, Any]:
    categories_by_slug, categories = _ensure_category_lookup()
    if not categories:
        return {"category_id": None, "category_slug": None, "confidence": 0.0, "method": "none", "reason": "no_categories"}

    rule_cat, rule_conf, rule_reason = _rule_pick(issue_text, categories)
    if rule_cat and rule_conf >= 0.65:
        return {
            "category_id": str(rule_cat.id),
            "category_slug": rule_cat.slug,
            "default_radius_km": rule_cat.__dict__.get("default_radius_km", 25),
            "confidence": round(rule_conf, 4),
            "method": "rules",
            "reason": rule_reason,
        }

    ml_cat, ml_conf, ml_reason = _ml_predict(issue_text, categories_by_slug)
    if ml_cat and ml_conf >= ML_CONFIDENCE_THRESHOLD:
        return {
            "category_id": str(ml_cat.id),
            "category_slug": ml_cat.slug,
            "default_radius_km": ml_cat.__dict__.get("default_radius_km", 25),
            "confidence": round(ml_conf, 4),
            "method": "ml",
            "reason": ml_reason,
        }

    fallback = _pick_fallback(categories)
    return {
        "category_id": str(fallback.id),
        "category_slug": fallback.slug,
        "default_radius_km": fallback.__dict__.get("default_radius_km", 25),
        "confidence": round(ml_conf if ml_cat else 0.3, 4),
        "method": "fallback",
        "reason": (
            f"ml_low_confidence:{round(ml_conf, 4)}"
            if ml_cat and ml_conf < ML_CONFIDENCE_THRESHOLD
            else (ml_reason if "ml_reason" in locals() else rule_reason)
        ),
    }


def train_issue_model(text: str, category_slug: str) -> None:
    tokens = _tokenize(text)
    if not tokens or not category_slug:
        return
    with _MODEL_LOCK:
        model = _load_model()
        classes = model.setdefault("classes", {})
        vocab = model.setdefault("vocabulary", {})
        slot = classes.setdefault(category_slug, {"doc_count": 0, "token_total": 0, "tokens": {}})
        slot["doc_count"] = int(slot.get("doc_count", 0)) + 1
        token_map = slot.setdefault("tokens", {})
        for token in tokens:
            token_map[token] = int(token_map.get(token, 0)) + 1
            slot["token_total"] = int(slot.get("token_total", 0)) + 1
            vocab[token] = int(vocab.get(token, 0)) + 1
        _save_model(model)


def train_from_service_request(sr: ServiceRequest) -> None:
    if not sr or not sr.category_id:
        return
    train_issue_model(sr.description or "", sr.category.slug)
