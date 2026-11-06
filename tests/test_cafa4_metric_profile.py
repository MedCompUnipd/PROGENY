"""Small independent set oracle for the implemented macro and semantic formulas."""

import math
import unittest

from progeny.prediction_metrics import evaluate_scores
from progeny.prediction_weighted_metrics import evaluate_weighted_scores


def test_macro_and_semantic_curves_match_direct_set_formulas():
    truth = {
        ("a", "F"): {"GO:0000001", "GO:0000002"},
        ("b", "F"): {"GO:0000003"},
        ("c", "F"): {"GO:0000002"},
    }
    scores = {
        ("a", "F", "GO:0000001"): 0.9,
        ("a", "F", "GO:0000004"): 0.8,
        ("b", "F", "GO:0000003"): 0.4,
        ("c", "F", "GO:0000004"): 0.2,
    }
    ia = {"GO:0000001": 2.0, "GO:0000002": 3.0, "GO:0000003": 4.0, "GO:0000004": 1.0}
    thresholds = [0.1, 0.3, 0.5, 0.95]
    args = {
        "eligible": set(truth),
        "truth": truth,
        "scores": scores,
        "species": {q: "9606" for q, _ in truth},
        "aspects": ["F"],
        "thresholds": thresholds,
    }
    raw = evaluate_scores(**args)["aspects"]["F"]["curve"]
    weighted = evaluate_weighted_scores(**args, information_accretion=ia)
    weighted = weighted["F"]["curve"]
    close = unittest.TestCase().assertAlmostEqual
    for row, wr in zip(raw, weighted, strict=True):
        tau = row["threshold"]
        p, r, wp, wrec = [], [], [], []
        fn, fp = 0.0, 0.0
        for (query, _), target in truth.items():
            pred = {
                go
                for (q, _, go), score in scores.items()
                if q == query and score >= tau
            }
            hit = pred & target
            if pred:
                p.append(len(hit) / len(pred))
                wp.append(sum(ia[t] for t in hit) / sum(ia[t] for t in pred))
            r.append(len(hit) / len(target))
            wrec.append(sum(ia[t] for t in hit) / sum(ia[t] for t in target))
            fn += sum(ia[t] for t in target - pred)
            fp += sum(ia[t] for t in pred - target)
        precision = sum(p) / len(p) if p else 0.0
        recall = sum(r) / len(truth)
        close(row["precision"], precision)
        close(row["recall_full"], recall)
        close(wr["weighted_precision"], sum(wp) / len(wp) if wp else 0.0)
        close(wr["weighted_recall"], sum(wrec) / len(truth))
        close(wr["ru"], fn / len(truth))
        close(wr["mi"], fp / len(truth))
        close(wr["smin"], math.hypot(fn, fp) / len(truth))


if __name__ == "__main__":
    test_macro_and_semantic_curves_match_direct_set_formulas()
    print("INDEPENDENT_MACRO_AND_SEMANTIC_ORACLE=PASS")
