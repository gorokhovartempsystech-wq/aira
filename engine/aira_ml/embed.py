"""Векторизация требований.

Основная модель — deepvk/USER-bge-m3: лидер бенчмарка на 7 моделях (F1 0,836
по дублям, но порог подобран на тех же 100 парах). Для тестов и машин без
модели — TF-IDF по символьным n-граммам: тот же интерфейс, без скачивания.
"""
from __future__ import annotations

import hashlib

import numpy as np

MODEL_NAME = "deepvk/USER-bge-m3"


class TfidfEmbedder:
    name = "tfidf-char"

    def encode(self, texts):
        # словарь строится на каждом вызове: запрос и кандидатов всегда кодируем вместе
        from sklearn.feature_extraction.text import TfidfVectorizer
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True)
        m = vec.fit_transform(texts).toarray().astype(np.float32)
        n = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(n == 0, 1, n)


class STEmbedder:
    def __init__(self, model_name=MODEL_NAME, device=None):
        from sentence_transformers import SentenceTransformer
        self.name = model_name
        self._m = SentenceTransformer(model_name, device=device)
        self._cache: dict[str, np.ndarray] = {}

    def encode(self, texts):
        keys = [hashlib.sha1(t.encode()).hexdigest() for t in texts]
        new = [(k, t) for k, t in zip(keys, texts) if k not in self._cache]
        if new:
            vecs = self._m.encode([t for _, t in new], normalize_embeddings=True,
                                  batch_size=32, show_progress_bar=False)
            for (k, _), v in zip(new, vecs):
                self._cache[k] = np.asarray(v, dtype=np.float32)
        return np.stack([self._cache[k] for k in keys])


def default_embedder():
    """USER-bge-m3, если доступна; иначе TF-IDF — сервис не падает без модели."""
    try:
        import torch
        return STEmbedder(device="cuda" if torch.cuda.is_available() else "cpu")
    except Exception:
        return TfidfEmbedder()
