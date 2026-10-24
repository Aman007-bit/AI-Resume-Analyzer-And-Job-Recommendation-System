import builtins
import importlib.util
import unittest
from unittest.mock import patch

from services.recommendation_service import calculate_tfidf_cosine_scores


RESUME = "Python developer builds APIs with FastAPI and SQL databases"
DESCRIPTIONS = [
    "Build Python APIs with FastAPI and work with SQL databases",
    "Provide in-person customer support and manage retail inventory",
]


def _import_without_sklearn(name, *args, **kwargs):
    if name == "sklearn" or name.startswith("sklearn."):
        raise ModuleNotFoundError("forced absent scikit-learn", name="sklearn")
    return _ORIGINAL_IMPORT(name, *args, **kwargs)


_ORIGINAL_IMPORT = builtins.__import__


class TfidfRecommendationTests(unittest.TestCase):
    def test_fallback_runs_when_sklearn_import_is_forced_unavailable(self):
        with patch("builtins.__import__", side_effect=_import_without_sklearn):
            scores = calculate_tfidf_cosine_scores(RESUME, DESCRIPTIONS)

        self.assertEqual(len(scores), 2)
        self.assertGreater(scores[0], scores[1])
        self.assertGreater(scores[0], 0)

    @unittest.skipUnless(
        importlib.util.find_spec("sklearn"), "scikit-learn is not installed"
    )
    def test_installed_scikit_learn_implementation_is_used(self):
        imported = []

        def track_sklearn_imports(name, *args, **kwargs):
            if name.startswith("sklearn."):
                imported.append(name)
            return _ORIGINAL_IMPORT(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=track_sklearn_imports):
            scores = calculate_tfidf_cosine_scores(RESUME, DESCRIPTIONS)

        self.assertIn("sklearn.feature_extraction.text", imported)
        self.assertIn("sklearn.metrics.pairwise", imported)
        self.assertGreater(scores[0], scores[1])

    def test_empty_resume_text_returns_zero_scores(self):
        self.assertEqual(
            calculate_tfidf_cosine_scores(None, DESCRIPTIONS), [0.0, 0.0]
        )

    def test_fallback_empty_vocabulary_returns_zero_scores(self):
        with patch("builtins.__import__", side_effect=_import_without_sklearn):
            scores = calculate_tfidf_cosine_scores("! ?", ["...", "??"])
        self.assertEqual(scores, [0.0, 0.0])

    def test_broken_sklearn_install_is_not_mistaken_for_absent_package(self):
        original_import = builtins.__import__

        def import_without_scipy(name, *args, **kwargs):
            if name == "sklearn" or name.startswith("sklearn."):
                raise ModuleNotFoundError("missing scipy dependency", name="scipy")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_scipy):
            with self.assertRaisesRegex(ModuleNotFoundError, "missing scipy"):
                calculate_tfidf_cosine_scores(RESUME, DESCRIPTIONS)

    @unittest.skipUnless(
        importlib.util.find_spec("sklearn"), "scikit-learn is not installed"
    )
    def test_scikit_learn_empty_vocabulary_returns_zero_scores(self):
        scores = calculate_tfidf_cosine_scores("! ?", ["...", "??"])
        self.assertEqual(scores, [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
