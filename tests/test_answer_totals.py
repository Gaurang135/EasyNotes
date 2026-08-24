"""Totals must be arithmetic-safe: the model reliably itemizes but slips on addition,
so the app recomputes any itemized total from the listed amounts and corrects it."""
from app.answer import reconcile_listed_total

# The real failure seen in production: 271.43+232.26+470.42+424.61+341.46 = 1740.18,
# but the model reported 1641.76.
FOOD = (
    "The total amount spent on food across the provided documents is 1,641.76.\n"
    "\n"
    "* **Order_Invoice8496177888** — 271.43 [Order_Invoice8496177888]\n"
    "* **Order_Invoice8502180726** — 232.26 [Order_Invoice8502180726]\n"
    "* **Order_Invoice8467373273** — 470.42 [Order_Invoice8467373273]\n"
    "* **Order_Invoice8504245215** — 424.61 [Order_Invoice8504245215]\n"
    "* **Order_Invoice8504587545** — 341.46 [Order_Invoice8504587545]"
)


def test_reconcile_fixes_wrong_llm_sum():
    fixed = reconcile_listed_total(FOOD)
    assert "1,740.18" in fixed
    assert "1,641.76" not in fixed


def test_reconcile_ignores_digits_inside_titles():
    # the long invoice numbers in the bullets must NOT be summed as amounts
    fixed = reconcile_listed_total(FOOD)
    assert "1,740.18" in fixed          # only the real amounts were summed


def test_reconcile_leaves_correct_total_untouched():
    good = FOOD.replace("1,641.76", "1,740.18")
    assert reconcile_listed_total(good) == good


def test_reconcile_noop_without_breakdown():
    ans = "The vendor is Northwind Traders and their email is ap@northwind.example [invoice_northwind]."
    assert reconcile_listed_total(ans) == ans


def test_reconcile_handles_currency_prefixes():
    ans = "Total: Rs.100.00\n* A — Rs.30.00 [A]\n* B — Rs.90.00 [B]"
    fixed = reconcile_listed_total(ans)
    assert "120.00" in fixed and "100.00" not in fixed
