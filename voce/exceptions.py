"""Custom exception hierarchy for Voce."""


class VoceError(Exception):
    """Base class for all Voce exceptions."""


class FeedFetchError(VoceError):
    """Raised when an RSS feed cannot be retrieved."""

    def __init__(self, slug: str, url: str, cause: Exception) -> None:
        self.slug = slug
        self.url = url
        self.cause = cause
        super().__init__(f"Failed to fetch feed '{slug}' at {url}: {cause}")


class ArticleFetchError(VoceError):
    """Raised when an article's full content cannot be retrieved."""

    def __init__(self, url: str, cause: Exception) -> None:
        self.url = url
        self.cause = cause
        super().__init__(f"Failed to fetch article at {url}: {cause}")


class ArticleParseError(VoceError):
    """Raised when article HTML cannot be parsed into readable text."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Failed to parse article at {url}: {reason}")


class TTSSynthesisError(VoceError):
    """Raised when text-to-speech synthesis fails for an article."""

    def __init__(self, article_id: str, cause: Exception) -> None:
        self.article_id = article_id
        self.cause = cause
        super().__init__(f"TTS synthesis failed for article '{article_id}': {cause}")


class ArticleNotFoundError(VoceError):
    """Raised when an article ID does not exist in the database."""

    def __init__(self, article_id: str) -> None:
        self.article_id = article_id
        super().__init__(f"Article '{article_id}' not found")


class ArticleTextMissingError(VoceError):
    """Raised when an article exists but has no extracted body text."""

    def __init__(self, article_id: str) -> None:
        self.article_id = article_id
        super().__init__(f"Article '{article_id}' has no body text")
