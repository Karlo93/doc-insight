"""Exercise the production loaders so an image contains exactly their pinned artifacts."""

from doc_insight.worker.embedder import FastEmbedEmbedder
from doc_insight.worker.providers import HfTokenizer
from doc_insight.worker.settings import get_settings

settings = get_settings()
assert HfTokenizer(settings).encode("Zagreb")
assert len(FastEmbedEmbedder(settings).embed_query("Zagreb")) == 384
