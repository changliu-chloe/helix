"""4-dimension scoring: relevance / recency / popularity / quality.

Ported from ref/evil-read-arxiv's scoring logic, refactored to operate on Paper.
Weights are driven by score_weights in config.yaml (falls back to DEFAULT_WEIGHTS).
"""

from __future__ import annotations

from datetime import datetime, timezone

from .config import Config, Domain
from .models import Paper

# Full raw score per dimension (normalization baseline)
SCORE_MAX = 3.0

# Relevance: boosts for keyword/category matches
RELEVANCE_TITLE_KEYWORD_BOOST = 0.5
RELEVANCE_SUMMARY_KEYWORD_BOOST = 0.3
RELEVANCE_CATEGORY_MATCH_BOOST = 1.0

# Recency thresholds (days -> score)
RECENCY_THRESHOLDS = [(30, 3.0), (90, 2.0), (180, 1.0)]
RECENCY_DEFAULT = 0.0

# Popularity: citation count at/above this is treated as full score
POPULARITY_CITATION_FULL_SCORE = 100

DEFAULT_WEIGHTS = {
    "relevance": 0.40,
    "recency": 0.20,
    "popularity": 0.30,
    "quality": 0.10,
}

# Word lists for inferring quality
_STRONG_INNOVATION = ["state-of-the-art", "sota", "breakthrough", "first", "surpass", "outperform", "pioneering"]
_WEAK_INNOVATION = ["novel", "propose", "introduce", "new approach", "new method", "innovative"]
_METHOD_INDICATORS = ["framework", "architecture", "algorithm", "mechanism", "pipeline", "end-to-end"]
_QUANTITATIVE_INDICATORS = ["outperforms", "improves by", "achieves", "accuracy", "f1", "bleu", "rouge", "beats", "surpasses"]
_EXPERIMENT_INDICATORS = ["experiment", "evaluation", "benchmark", "ablation", "baseline", "comparison"]


def _parse_date(iso: str) -> datetime | None:
    """Parse an ISO date string into a datetime (tolerant of several formats)."""
    if not iso:
        return None
    s = iso.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(iso[: len(fmt) + 2], fmt)
        except ValueError:
            continue
    return None


def relevance_score(paper: Paper, domains: list[Domain], excluded: list[str]) -> tuple[float, str | None, list[str]]:
    """Relevance score. Returns (score, best domain, matched keywords). Returns 0 if an excluded keyword hits."""
    title = (paper.title or "").lower()
    summary = (paper.abstract or "").lower()
    categories = set(paper.categories or [])

    for kw in excluded:
        k = kw.lower()
        if k and (k in title or k in summary):
            return 0.0, None, []

    best_score = 0.0
    best_domain: str | None = None
    best_matched: list[str] = []

    for d in domains:
        score = 0.0
        matched: list[str] = []
        for kw in d.keywords:
            k = kw.lower()
            if k in title:
                score += RELEVANCE_TITLE_KEYWORD_BOOST
                matched.append(kw)
            elif k in summary:
                score += RELEVANCE_SUMMARY_KEYWORD_BOOST
                matched.append(kw)
        for cat in d.arxiv_categories:
            if cat in categories:
                score += RELEVANCE_CATEGORY_MATCH_BOOST
                matched.append(cat)
        if score > best_score:
            best_score, best_domain, best_matched = score, d.name, matched

    return best_score, best_domain, best_matched


def recency_score(published: str, now: datetime | None = None) -> float:
    dt = _parse_date(published)
    if dt is None:
        return RECENCY_DEFAULT
    ref = now or (datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now())
    days = (ref - dt).days
    for max_days, s in RECENCY_THRESHOLDS:
        if days <= max_days:
            return s
    return RECENCY_DEFAULT


def popularity_score(paper: Paper) -> float:
    """Normalize by citation count when available; otherwise approximate a new paper's "potential popularity"."""
    if paper.citation_count is not None:
        return min(paper.citation_count / (POPULARITY_CITATION_FULL_SCORE / SCORE_MAX), SCORE_MAX)
    dt = _parse_date(paper.published)
    if dt is None:
        return 0.5
    ref = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    days = (ref - dt).days
    if days <= 7:
        return 2.0
    if days <= 14:
        return 1.5
    if days <= 30:
        return 1.0
    return 0.5


def quality_score(abstract: str) -> float:
    if not abstract:
        return 0.0
    s = abstract.lower()
    score = 0.0
    strong = sum(1 for w in _STRONG_INNOVATION if w in s)
    if strong >= 2:
        score += 1.0
    elif strong == 1:
        score += 0.7
    elif any(w in s for w in _WEAK_INNOVATION):
        score += 0.3
    if any(w in s for w in _METHOD_INDICATORS):
        score += 0.5
    if any(w in s for w in _QUANTITATIVE_INDICATORS):
        score += 0.8
    elif any(w in s for w in _EXPERIMENT_INDICATORS):
        score += 0.4
    return min(score, SCORE_MAX)


def final_score(rel: float, rec: float, pop: float, qual: float, weights: dict[str, float]) -> float:
    """Normalize the four dimensions to 0-10, then compute a weighted sum."""
    raw = {"relevance": rel, "recency": rec, "popularity": pop, "quality": qual}
    normalized = {k: (v / SCORE_MAX) * 10 for k, v in raw.items()}
    total = sum(normalized[k] * weights.get(k, DEFAULT_WEIGHTS[k]) for k in DEFAULT_WEIGHTS)
    return round(total, 2)


def score_papers(papers: list[Paper], cfg: Config) -> list[Paper]:
    """Score papers in bulk and sort by final score descending. Papers with relevance 0 are dropped."""
    weights = cfg.score_weights or DEFAULT_WEIGHTS
    scored: list[Paper] = []
    for p in papers:
        rel, domain, matched = relevance_score(p, cfg.domains, cfg.excluded_keywords)
        if rel == 0:
            continue
        rec = recency_score(p.published)
        pop = popularity_score(p)
        qual = quality_score(p.abstract)
        p.score_relevance = round(rel, 2)
        p.score_recency = round(rec, 2)
        p.score_popularity = round(pop, 2)
        p.score_quality = round(qual, 2)
        p.score_final = final_score(rel, rec, pop, qual, weights)
        p.matched_domains = [domain] if domain else []
        p.matched_keywords = matched
        scored.append(p)
    scored.sort(key=lambda x: x.score_final, reverse=True)
    return scored
