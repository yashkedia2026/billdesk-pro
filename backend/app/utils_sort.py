from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple


_PR_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])PR\s*0*(\d+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def extract_pr_number(value: object) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None

    match = _PR_NUMBER_PATTERN.search(text)
    if not match:
        return None

    return int(match.group(1))


def natural_pr_sort_key(value: object) -> Tuple[int, int, str]:
    text = str(value or "").strip()
    lower = text.lower()
    pr_number = extract_pr_number(text)

    if _is_non_pr_document(lower):
        group_rank = 0
    elif _is_pr_account_item(lower, pr_number):
        group_rank = 1
    else:
        group_rank = 2

    pr_rank = pr_number if pr_number is not None else 10**9
    return (group_rank, pr_rank, lower)


def sort_values_natural_pr(values: Iterable[str]) -> List[str]:
    return sorted((str(value) for value in values), key=natural_pr_sort_key)


def _is_non_pr_document(lower_text: str) -> bool:
    return lower_text.startswith("summary_") or lower_text.startswith("bill_admin_")


def _is_pr_account_item(lower_text: str, pr_number: Optional[int]) -> bool:
    if pr_number is None:
        return False
    if lower_text.startswith("pr"):
        return True
    return lower_text.startswith("bill_") and not lower_text.startswith("bill_admin_")
