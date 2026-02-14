from app.utils_sort import extract_pr_number, natural_pr_sort_key, sort_values_natural_pr


def test_extract_pr_number_handles_padded_and_unpadded_values() -> None:
    assert extract_pr_number("PR05") == 5
    assert extract_pr_number("PR5") == 5
    assert extract_pr_number("Bill_PR10_2026-02-12.pdf") == 10
    assert extract_pr_number("Summary_Admin_Closing_Adjustment_2026-02-12.pdf") is None


def test_sort_values_natural_pr_orders_summary_then_pr_account_pdfs() -> None:
    filenames = [
        "Bill_PR10_2026-02-12.pdf",
        "Bill_PR05_2026-02-12.pdf",
        "Bill_PR6_2026-02-12.pdf",
        "Summary_Admin_Closing_Adjustment_2026-02-12.pdf",
    ]

    assert sort_values_natural_pr(filenames) == [
        "Summary_Admin_Closing_Adjustment_2026-02-12.pdf",
        "Bill_PR05_2026-02-12.pdf",
        "Bill_PR6_2026-02-12.pdf",
        "Bill_PR10_2026-02-12.pdf",
    ]


def test_natural_pr_sort_key_keeps_non_pr_documents_before_pr_documents() -> None:
    ordered = sorted(
        [
            "Bill_PR05_2026-02-12.pdf",
            "manifest.json",
            "Bill_Admin_2026-02-12.pdf",
            "Summary_Admin_Closing_Adjustment_2026-02-12.pdf",
        ],
        key=natural_pr_sort_key,
    )

    assert ordered == [
        "Bill_Admin_2026-02-12.pdf",
        "Summary_Admin_Closing_Adjustment_2026-02-12.pdf",
        "Bill_PR05_2026-02-12.pdf",
        "manifest.json",
    ]
