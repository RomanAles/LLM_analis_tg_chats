"""Compatibility entry point for the original purchase extractor."""
from tg_chat_analyzer.legacy import (
    ModelResponseError, TransformersGenerator, analyze_window, collect_purchases,
    extract_text, main, parse_purchase,
)

if __name__ == "__main__":
    raise SystemExit(main())
