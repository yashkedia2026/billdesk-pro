from app.charges_edit import apply_user_edits


def _base_charges():
    return {
        "bill_lines": [
            {"code": "TOC_NSE", "label": "TOC NSE Exchange", "amount": -100.0},
            {"code": "TOC_BSE", "label": "TOC BSE Exchange", "amount": -50.0},
            {"code": "CLEARING", "label": "Clearing Charges", "amount": -10.0},
            {"code": "SEBI", "label": "SEBI Fees", "amount": -5.0},
            {"code": "STT", "label": "STT", "amount": -20.0},
            {"code": "CGST_9", "label": "CGST @ 9%", "amount": -14.85},
            {"code": "SGST_9", "label": "SGST @ 9%", "amount": -14.85},
        ],
        "net_amount": 1000.0,
        "total_expenses": -200.0,
        "total_bill_amount": 800.0,
        "gst_base": 165.0,
        "gst_total": 29.7,
    }


def test_override_changes_only_one_line():
    charges = _base_charges()
    updated = apply_user_edits(
        charges, overrides=[{"code": "TOC_NSE", "amount": 200}], additions=[]
    )
    toc_nse = next(line for line in updated["bill_lines"] if line["code"] == "TOC_NSE")
    toc_bse = next(line for line in updated["bill_lines"] if line["code"] == "TOC_BSE")
    assert toc_nse["amount"] == -200
    assert toc_bse["amount"] == -50


def test_addition_appends_after_computed():
    charges = _base_charges()
    updated = apply_user_edits(
        charges,
        overrides=[],
        additions=[{"name": "Interest", "amount": 12.5, "gst_applicable": False}],
    )
    last_line = updated["bill_lines"][-1]
    assert last_line["label"] == "Interest"
    assert last_line["amount"] == -12.5


def test_duplicate_name_rejected():
    charges = _base_charges()
    try:
        apply_user_edits(
            charges,
            overrides=[],
            additions=[{"name": "TOC NSE Exchange", "amount": 10}],
        )
    except ValueError as exc:
        assert "Charge already exists" in str(exc)
    else:
        raise AssertionError("Expected duplicate name error")


def test_gst_recomputed_after_override():
    charges = _base_charges()
    updated = apply_user_edits(
        charges,
        overrides=[{"code": "TOC_NSE", "amount": 200}],
        additions=[],
    )
    gst_base = updated["gst_base"]
    assert gst_base == 265.0
    cgst = next(line for line in updated["bill_lines"] if line["code"] == "CGST_9")
    sgst = next(line for line in updated["bill_lines"] if line["code"] == "SGST_9")
    assert cgst["amount"] == -23.85
    assert sgst["amount"] == -23.85
    assert updated["total_bill_amount"] == 667.3


def test_duplicate_vs_computed_case_insensitive():
    charges = _base_charges()
    try:
        apply_user_edits(
            charges,
            overrides=[],
            additions=[{"name": "stt", "amount": 5}],
        )
    except ValueError as exc:
        assert "Charge already exists" in str(exc)
    else:
        raise AssertionError("Expected duplicate name error")


def test_duplicate_among_additions_case_insensitive():
    charges = _base_charges()
    try:
        apply_user_edits(
            charges,
            overrides=[],
            additions=[
                {"name": "Interest", "amount": 10},
                {"name": " interest ", "amount": 5},
            ],
        )
    except ValueError as exc:
        assert "Charge already exists" in str(exc)
    else:
        raise AssertionError("Expected duplicate additions error")


def test_whitespace_collapse_for_label():
    charges = _base_charges()
    updated = apply_user_edits(
        charges,
        overrides=[],
        additions=[{"name": "Software   Charges", "amount": 10}],
    )
    assert updated["bill_lines"][-1]["label"] == "Software Charges"
