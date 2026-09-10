from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from doc_insight.testing.structure import FakeTokenizer
from doc_insight.worker import embedder
from doc_insight.worker.embedder import FastEmbedEmbedder
from doc_insight.worker.extraction import extract
from doc_insight.worker.settings import Settings
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer


def test_adapter_pins_downloads_reuses_model_and_passes_batch_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    download = Mock(return_value=str(tmp_path))
    model = Mock()
    model.embed.return_value = [np.ones(384)]
    factory = Mock(return_value=model)
    monkeypatch.setattr(embedder, "snapshot_download", download)
    monkeypatch.setattr("fastembed.TextEmbedding", factory)
    monkeypatch.setattr(embedder, "HfTokenizer", lambda settings: FakeTokenizer())
    settings = Settings(model_cache=tmp_path, embed_batch=7)
    for _ in range(2):
        result = FastEmbedEmbedder(settings).embed_query("hello")
        assert result == pytest.approx([1 / 384**0.5] * 384)
    assert download.call_count == factory.call_count == 1
    assert download.call_args.kwargs["revision"] == settings.embed_revision
    assert download.call_args.kwargs["cache_dir"] == tmp_path
    assert factory.call_args.kwargs["specific_model_path"] == str(tmp_path)
    assert factory.call_args.kwargs["providers"] == ["CPUExecutionProvider"]
    model.embed.assert_called_with(["hello"], batch_size=7)


def test_entire_batch_is_checked_before_loading_or_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = Mock()
    monkeypatch.setattr("fastembed.TextEmbedding", factory)
    monkeypatch.setattr(embedder, "HfTokenizer", lambda settings: FakeTokenizer())
    adapter = FastEmbedEmbedder(Settings())
    assert adapter.embed_passages([]) == []
    with pytest.raises(ValueError, match="refusing truncation"):
        adapter.embed_passages(["short", "private " * 127])
    factory.assert_not_called()


@pytest.mark.models
def test_real_model_accepts_126_tokens_and_rejects_127() -> None:
    adapter = FastEmbedEmbedder(Settings())
    assert len(adapter.embed_query("the " * 126)) == 384
    with pytest.raises(ValueError, match="126 content tokens"):
        adapter.embed_query("the " * 127)


@pytest.mark.models
def test_onnx_and_chunking_tokenizers_agree_on_fixture_text() -> None:
    settings = Settings()
    tokenizers = []
    for repo, revision in [
        (settings.embed_model, settings.tokenizer_revision),
        (settings.embed_onnx_repo, settings.embed_revision),
    ]:
        path = hf_hub_download(
            repo, "tokenizer.json", revision=revision, cache_dir=settings.model_cache
        )
        tokenizer = Tokenizer.from_file(path)
        tokenizer.no_padding()
        tokenizer.no_truncation()
        tokenizers.append(tokenizer)
    fixtures = Path(__file__).parent / "fixtures"
    texts = ["", "Čćđšž Zagreb 😀."]
    for name in ["text_en.pdf", "text_hr.pdf", "text_long.pdf"]:
        texts.extend(page.text for page in extract(fixtures / name).pages)
    for text in texts:
        assert tokenizers[0].encode(text).ids == tokenizers[1].encode(text).ids
