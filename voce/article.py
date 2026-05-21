"""HTML-to-text extraction and LaTeX substitution for TTS narration."""

from __future__ import annotations

import re

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
