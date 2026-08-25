"""Ask must aggregate over full table rows in code — retrieval only shows the model a
subset of a big table, so counts/sums/averages have to be computed deterministically."""
from app.search.tableagg import compute_table_facts

EMP = {"name": "employees",
       "columns": [{"name": "emp_id", "type": "text"}, {"name": "department", "type": "text"},
                   {"name": "annual_salary_inr", "type": "number"},
                   {"name": "monthly_salary_inr", "type": "number"}],
       "rows": [["EMP1", "Engineering", 1200000, 100000],
                ["EMP2", "Sales", 600000, 50000],
                ["EMP3", "Engineering", 2400000, 200000]]}
# annual sum = 4,200,000 · engineering count = 2 · monthly sum = 350,000
ORD = {"name": "orders",
       "columns": [{"name": "order_id", "type": "text"}, {"name": "status", "type": "text"},
                   {"name": "total_inr", "type": "number"}],
       "rows": [["O1", "paid", 1000], ["O2", "refunded", 2000], ["O3", "paid", 3000]]}
# total_inr sum = 6,000 · refunded count = 1
TABLES = [EMP, ORD]


def _joined(facts):
    return " || ".join(facts)


def test_sum_named_column():
    f = _joined(compute_table_facts(TABLES, "what is the total annual salary of all employees?"))
    assert "annual_salary_inr" in f and "4,200,000" in f
    assert "monthly" not in f            # picked the right salary column


def test_count_with_filter():
    f = _joined(compute_table_facts(TABLES, "how many employees are in the Engineering department?"))
    assert "employees" in f and "Engineering" in f and "= 2" in f


def test_sum_via_table_name_and_measure_fallback():
    # no column-name overlap ("value"), but the table is named and total_inr is the measure col
    f = _joined(compute_table_facts(TABLES, "what is the total value of all orders?"))
    assert "total_inr" in f and "6,000" in f


def test_count_with_status_filter():
    f = _joined(compute_table_facts(TABLES, "how many refunded orders are there?"))
    assert "= 1" in f


def test_average():
    f = _joined(compute_table_facts(TABLES, "what is the average annual salary?"))
    assert "1,400,000" in f            # 4,200,000 / 3


def test_no_op_returns_nothing():
    assert compute_table_facts(TABLES, "who is the vendor and their email?") == []


def test_document_count_is_not_a_table_fact():
    # "documents" is not a table name and matches no filter → leave it to structured_context
    assert compute_table_facts(TABLES, "how many documents do I have?") == []


def test_unrelated_total_does_not_fire_on_tables():
    # invoice total lives in fields, not these tables — must NOT invent a table sum
    assert compute_table_facts(TABLES, "what is the total amount on the vendor invoice?") == []
