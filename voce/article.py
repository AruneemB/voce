"""HTML-to-text extraction and LaTeX substitution for TTS narration."""

from __future__ import annotations

import re
import sqlite3

import httpx
from loguru import logger

from voce.exceptions import ArticleFetchError, ArticleParseError

_LATEX_SUBS: list[tuple[str, str]] = [
    (r"\\frac\{([^}]+)\}\{([^}]+)\}", r"\1 over \2"),
    (r"\\sqrt\{([^}]+)\}", r"the square root of \1"),
    (r"\^\{(\w+)\}", r" to the power of \1"),
    (r"\^(\w)", r" to the power of \1"),
    (r"_\{(\w+)\}", r" sub \1"),
    (r"_(\w)", r" sub \1"),
    (r"\\infty", "infinity"),
    (r"\\sum", "sum"),
    (r"\\int", "integral"),
    (r"\\prod", "product"),
    (r"\\Delta", "delta"),
    (r"\\nabla", "nabla"),
    (r"\\partial", "partial"),
    (r"\\pi", "pi"),
    (r"\\theta", "theta"),
    (r"\\alpha", "alpha"),
    (r"\\beta", "beta"),
    (r"\\gamma", "gamma"),
    (r"\\lambda", "lambda"),
    (r"\\mu", "mu"),
    (r"\\sigma", "sigma"),
    (r"\\epsilon", "epsilon"),
    (r"\\rho", "rho"),
    (r"\\phi", "phi"),
    (r"\\omega", "omega"),
    (r"\$\$[^$]+\$\$", ""),
    (r"\$[^$]+\$", ""),
    (r"\\[a-zA-Z]+", ""),
    (r"[{}]", " "),
]


def apply_latex_substitutions(text: str) -> str:
    for pattern, replacement in _LATEX_SUBS:
        text = re.sub(pattern, replacement, text)
    return text


def count_words(text: str) -> int:
    return len(text.split())


_REMOVE_TAGS = {"script", "style", "aside", "figure", "iframe", "noscript"}
_REMOVE_CLASS_SUBSTRINGS = {"share", "newsletter", "related", "byline", "sidebar"}
_OL_ORDINALS = [
    "First", "Second", "Third", "Fourth", "Fifth",
    "Sixth", "Seventh", "Eighth", "Ninth",
]


def clean_html_for_tts(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    for tag_name in _REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class") or []).lower()
        if any(sub in classes for sub in _REMOVE_CLASS_SUBSTRINGS):
            tag.decompose()

    for br in soup.find_all("br"):
        br.replace_with("\n")

    for level in range(1, 7):
        for tag in soup.find_all(f"h{level}"):
            tag.replace_with(f"\n\n{tag.get_text(strip=True)}.\n\n")

    for tag in soup.find_all("blockquote"):
        tag.replace_with(f"\n\nQuote: {tag.get_text(strip=True)} End quote.\n\n")

    for ol in soup.find_all("ol"):
        items = ol.find_all("li")
        parts = []
        for n, li in enumerate(items, start=1):
            ordinal = _OL_ORDINALS[n - 1] if n <= 9 else f"{n}."
            parts.append(f"{ordinal}, {li.get_text(strip=True)}.")
        ol.replace_with(" ".join(parts))

    for ul in soup.find_all("ul"):
        items = [li.get_text(strip=True) for li in ul.find_all("li")]
        if len(items) == 0:
            ul.replace_with("")
        elif len(items) == 1:
            ul.replace_with(items[0])
        else:
            ul.replace_with(", ".join(items[:-1]) + ", and " + items[-1])

    text = soup.get_text(separator=" ", strip=True)
    text = apply_latex_substitutions(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


_FETCH_HEADERS = {"User-Agent": "Voce/0.1 (personal TTS companion; +local)"}
_FETCH_TIMEOUT = 20


def build_preamble(title: str, author: str | None, published_at: str) -> str:
    return (
        f"From Quanta Magazine. {title}. "
        f"By {author or 'Quanta Magazine'}. "
        f"Published {published_at[:10]}."
    )


def fetch_article_html(url: str, client: httpx.Client) -> str:
    try:
        response = client.get(url, headers=_FETCH_HEADERS, timeout=_FETCH_TIMEOUT)
    except httpx.RequestError as exc:
        raise ArticleFetchError(url, exc) from exc
    if not response.is_success:
        raise ArticleFetchError(url, ValueError(f"HTTP {response.status_code}"))
    return response.text


def enrich_article(
    article_id: str,
    url: str,
    body_html: str,
    conn: sqlite3.Connection,
    client: httpx.Client,
) -> bool:
    try:
        if body_html:
            body_text = clean_html_for_tts(body_html)
        else:
            body_html = fetch_article_html(url, client)
            body_text = clean_html_for_tts(body_html)
    except (ArticleFetchError, ArticleParseError) as exc:
        logger.warning("Could not enrich article {}: {}", article_id, exc)
        return False

    row = conn.execute(
        "SELECT title, author, published_at FROM articles WHERE id=?",
        (article_id,),
    ).fetchone()

    preamble = build_preamble(row["title"], row["author"], row["published_at"])
    full_text = preamble + "\n\n" + body_text

    conn.execute(
        "UPDATE articles SET body_text=?, body_html=? WHERE id=?",
        (full_text, body_html, article_id),
    )
    conn.commit()
    return True


def enrich_all_unenriched(
    conn: sqlite3.Connection,
    client: httpx.Client,
) -> tuple[int, int]:
    rows = conn.execute(
        "SELECT id, url, body_html FROM articles WHERE body_text = '' OR body_text IS NULL"
    ).fetchall()

    success = 0
    failure = 0
    for row in rows:
        ok = enrich_article(row["id"], row["url"], row["body_html"] or "", conn, client)
        if ok:
            success += 1
        else:
            failure += 1
    return success, failure
