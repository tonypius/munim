import csv

from munim_ingest.csv_writer import write_csv


def test_write_csv_writes_rows_correctly(tmp_path):
    out_path = tmp_path / "out.csv"
    write_csv([["Date", "Amount"], ["2026-06-01", "100"]], out_path)

    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows == [["Date", "Amount"], ["2026-06-01", "100"]]


def test_write_csv_creates_parent_directory(tmp_path):
    out_path = tmp_path / "does" / "not" / "exist" / "out.csv"
    write_csv([["a"]], out_path)
    assert out_path.exists()


def test_write_csv_handles_ragged_rows(tmp_path):
    """The fallback (text-line) extraction path can produce single-column
    rows while a table path produces multi-column rows — csv.writer must
    not choke on rows of differing length in the same file."""
    out_path = tmp_path / "out.csv"
    write_csv([["Date", "Amount"], ["just one field"]], out_path)

    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows == [["Date", "Amount"], ["just one field"]]
