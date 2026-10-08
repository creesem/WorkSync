"""Spec 5 ticket 02: canonical similarity scoring."""

from __future__ import annotations

from worksync.work.similarity import score, title_jaccard, title_tokens, words


def test_words_drops_stopwords_and_punctuation() -> None:
    assert words("Call the Vendor, re: invoice!") == ["call", "vendor", "re", "invoice"]
    assert title_tokens("the A and B") == {"b"}


def test_title_jaccard_handles_empty() -> None:
    assert title_jaccard("", "anything") == 0.0
    assert title_jaccard("the and of", "x") == 0.0
    assert title_jaccard("call vendor", "call vendor") == 1.0


def test_score_orders_identical_above_partial() -> None:
    assert score("call the vendor", "call the vendor") == 1.0
    assert score("call the vendor", "call vendor") > 0.7
    assert score("call the vendor", "unrelated meeting") < 0.3
