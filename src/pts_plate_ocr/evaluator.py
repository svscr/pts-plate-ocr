from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

import cv2
import numpy as np

from .ocr import LocalPlateOcr
from .plate import clean_ocr_text


def evaluate(manifest_path: Path, output_path: Path) -> dict[str, object]:
    root = manifest_path.parent
    rows = list(csv.DictReader(manifest_path.read_text(encoding="utf-8-sig").splitlines()))
    ocr = LocalPlateOcr()
    results: list[dict[str, object]] = []
    for row in rows:
        image_path = (root / row["image_path"]).resolve()
        # OpenCV's Windows path handling is unreliable for Turkish characters.
        image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            results.append({**row, "status": "error", "error": "image_not_found"})
            continue
        started = time.perf_counter()
        result = ocr.analyze(image)
        elapsed = (time.perf_counter() - started) * 1000
        expected = clean_ocr_text(row["expected_plate"])
        results.append(
            {
                **row,
                "status": result.status.value,
                "expected_plate": expected,
                "predicted_plate": result.plate or "",
                "correct": result.plate == expected,
                "score": round(result.score, 4),
                "winning_variant": result.winning_variant or "",
                "latency_ms": round(elapsed, 1),
                "message": result.message,
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=sorted({key for item in results for key in item}))
        writer.writeheader()
        writer.writerows(results)
    complete = [item for item in results if item.get("status") != "error"]
    correct = [item for item in complete if item.get("correct")]
    high = [item for item in complete if item.get("status") == "high_confidence"]
    high_wrong = [item for item in high if not item.get("correct")]
    summary = {
        "samples": len(results),
        "exact_match": len(correct) / len(complete) if complete else 0.0,
        "high_confidence_count": len(high),
        "high_confidence_wrong": len(high_wrong),
        "median_latency_ms": statistics.median([item["latency_ms"] for item in complete]) if complete else 0.0,
        "report": str(output_path),
    }
    output_path.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="PTS Plaka OCR veri seti değerlendirme aracı")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("evaluation_report.csv"))
    arguments = parser.parse_args()
    print(json.dumps(evaluate(arguments.manifest, arguments.out), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
