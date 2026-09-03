"""Munim CLI. Designed so a non-developer goes from install to categorized
statement in five minutes: init -> import -> review -> report.
"""
from __future__ import annotations

import csv as csv_module
import json
from collections import defaultdict
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table

from .schema import Stage, Status, Transaction
from .store import Store
from .pipeline import Pipeline
from .ingest import load_csv, CsvProfile
from .fallback import SKLEARN_AVAILABLE

app = typer.Typer(help="Munim — a local bookkeeper that learns from you.",
                  no_args_is_help=True, add_completion=False)
console = Console()

DEFAULT_CATEGORIES = [
    "Groceries", "Dining", "Transport", "Fuel", "Shopping", "Subscriptions",
    "Utilities", "Rent", "Health", "Entertainment", "Travel",
    "Education", "Fees & Charges", "Income", "Investments", "Transfers",
    "Family & Friends", "Other",
]


def _store() -> Store:
    return Store()


# --------------------------------------------------------------------- init
@app.command()
def init(region: str = typer.Option("in", help="Region pack: in / us / generic"),
         currency: str = typer.Option("INR")):
    """Set up Munim: region, currency, categories. Run once."""
    store = _store()
    store.set_config("region", region)
    store.set_config("currency", currency)
    store.set_config("categories", DEFAULT_CATEGORIES)
    from .tree import default_tree
    store.set_config("category_tree", default_tree(DEFAULT_CATEGORIES))
    console.print(f"[green]Munim initialized[/green] at {store.home}")
    console.print(f"Region pack: [bold]{region}[/bold] · Currency: {currency}")
    console.print(f"Categories: {', '.join(DEFAULT_CATEGORIES)}")
    console.print("\nNext: [bold]munim import your-statement.csv[/bold]")
    if not SKLEARN_AVAILABLE:
        console.print(r"[dim]Tip: pip install 'munim\[ml]' enables the fallback "
                      "classifier for unknown merchants.[/dim]")


# ------------------------------------------------------------------- import
@app.command("import")
def import_csv(
    file: Path = typer.Argument(..., exists=True, help="Bank statement CSV"),
    profile: str = typer.Option("", help="Saved column profile name"),
    account: str = typer.Option("default", help="Account name (for transfer matching)"),
):
    """Import a statement CSV and classify it."""
    store = _store()
    prof = _load_or_build_profile(store, file, profile, account)
    txns = load_csv(file, prof)
    if not txns:
        console.print("[red]No transactions parsed — check the column mapping.[/red]")
        raise typer.Exit(1)

    pipeline = Pipeline(store)
    if not pipeline.matcher.dictionary:
        console.print("[red]Warning: the community dictionary loaded 0 "
                      "patterns — this is an installation problem, and "
                      "classification quality will collapse. Reinstall munim "
                      "and run munim doctor.[/red]")
    stats = pipeline.run(txns)
    inserted, skipped = store.upsert_transactions(txns)

    resolved = stats.total - stats.by_stage.get("none", 0)
    pct = 100 * resolved / stats.total if stats.total else 0
    console.print(f"\n[bold]{inserted}[/bold] transactions imported"
                  + (f" ({skipped} duplicates skipped)" if skipped else ""))
    console.print(f"[green]{resolved} classified automatically ({pct:.1f}%)[/green]")
    unresolved = stats.by_stage.get("none", 0)
    if unresolved:
        console.print(f"[yellow]{unresolved} need you[/yellow] → run: "
                      f"[bold]munim review[/bold]")
    _print_stage_table(stats.by_stage)


def _load_or_build_profile(store: Store, file: Path, name: str,
                           account: str) -> CsvProfile:
    profiles = store.get_config("csv_profiles", {})
    if name and name in profiles:
        data = profiles[name]
        data["account"] = account
        return CsvProfile(**data)

    # Interactive column-mapping wizard (runs once, saved for reuse)
    with open(file, newline="", encoding="utf-8-sig") as f:
        header = next(csv_module.reader(f))
    console.print("\n[bold]First import from this format — map the columns once:[/bold]")
    for i, col in enumerate(header):
        console.print(f"  [{i}] {col}")
    date_col = header[int(typer.prompt("Date column number"))]
    desc_col = header[int(typer.prompt("Description column number"))]
    mode = typer.prompt("Amounts: [1] one signed column  [2] separate debit/credit",
                        default="2")
    if mode.strip() == "1":
        amount_col = header[int(typer.prompt("Amount column number"))]
        prof = CsvProfile(date_col=date_col, description_col=desc_col,
                          amount_col=amount_col, account=account,
                          currency=store.get_config("currency", "INR"))
    else:
        debit_col = header[int(typer.prompt("Debit column number"))]
        credit_col = header[int(typer.prompt("Credit column number"))]
        prof = CsvProfile(date_col=date_col, description_col=desc_col,
                          debit_col=debit_col, credit_col=credit_col,
                          account=account,
                          currency=store.get_config("currency", "INR"))
    save_as = typer.prompt("Save this mapping as (e.g. 'hdfc')", default="default")
    profiles[save_as] = {k: v for k, v in prof.__dict__.items() if k != "extras"}
    store.set_config("csv_profiles", profiles)
    console.print(f"[dim]Saved — next time: munim import file.csv --profile {save_as}[/dim]")
    return prof


# ------------------------------------------------------------------- review
@app.command()
def review(limit: int = typer.Option(50, help="Max items this session")):
    """Confirm or correct classifications — the 2-minute weekly ritual."""
    store = _store()
    categories = store.get_config("categories", DEFAULT_CATEGORIES)
    queue = store.review_queue()[:limit]
    if not queue:
        console.print("[green]Queue is empty — everything is confirmed. "
                      "The munim rests.[/green]")
        return

    console.print(f"[bold]{len(queue)} to review.[/bold] "
                  "[Enter]=accept · number=pick category · s=skip · q=quit\n")
    confirmed = 0
    propagated = 0
    session_done: set[tuple[str, str]] = set()  # rules confirmed this session
    for i, t in enumerate(queue, 1):
        key = ("payee", t.payee_handle) if t.payee_handle \
            else ("merchant", t.merchant_norm)
        if key[1] and key in session_done:
            continue  # already resolved by propagation moments ago
        label = t.merchant_norm or t.payee_handle or t.description_raw[:40]
        console.print(f"[{i}/{len(queue)}] [bold]{label}[/bold]  "
                      f"{t.currency} {t.amount:,.2f}  {t.date}  ({t.direction.value})")
        console.print(f"        [dim]{t.description_raw[:70]}[/dim]")
        if t.category:
            console.print(f"        Suggested: [cyan]{t.category}[/cyan] "
                          f"[dim](via {t.stage.value}, {t.confidence:.0%})[/dim]")
        else:
            console.print("        [yellow]No suggestion — new merchant.[/yellow]")
        cols = "  ".join(f"[{j}]{c}" for j, c in enumerate(categories))
        console.print(f"        [dim]{cols}[/dim]")

        choice = typer.prompt("      →", default="", show_default=False).strip().lower()
        if choice == "q":
            break
        if choice == "s":
            continue
        if choice == "" and t.category:
            final = t.category
        elif choice.isdigit() and int(choice) < len(categories):
            final = categories[int(choice)]
        else:
            console.print("        [red]Skipped (unrecognized input).[/red]\n")
            continue

        # Loop 3: log prediction vs outcome for threshold calibration
        store.log_correction(t, final)
        # Loop 1: confirmed mapping enters memory forever. A subcategory
        # already on file for this pattern only survives if `final`
        # matches the category it was taught under — otherwise it no
        # longer applies and must be cleared.
        if t.payee_handle:
            sub = store.existing_subcategory(t.payee_handle, "payee", final)
            store.remember(t.payee_handle, final, kind="payee", subcategory=sub)
            n_more = store.propagate(t.payee_handle, final, "payee", t.id,
                                     subcategory=sub)
        elif t.merchant_norm:
            sub = store.existing_subcategory(t.merchant_norm, "merchant", final)
            store.remember(t.merchant_norm, final, kind="merchant", subcategory=sub)
            n_more = store.propagate(t.merchant_norm, final, "merchant", t.id,
                                     subcategory=sub)
        else:
            sub = ""
            n_more = 0
        if key[1]:
            session_done.add(key)
        t.category = final
        t.subcategory = sub
        # is_transfer must track the category, not just the structural
        # auto-detector: a transaction the auto-detector couldn't pair
        # (e.g. a credit-card bill payment where only the card's own
        # statement is imported) still needs this set when confirmed as
        # "Transfers" here — reports/dashboard check is_transfer, not the
        # category string. Also clears it when correcting a mis-flagged
        # transfer to a real category.
        t.is_transfer = final == "Transfers"
        t.stage = Stage.USER if choice else t.stage
        t.status = Status.CONFIRMED
        store.update_transaction(t)
        confirmed += 1
        propagated += n_more
        extra = f" (+{n_more} identical transactions)" if n_more else ""
        console.print(f"        [green]✓ {final}[/green] — remembered{extra}.\n")

    console.print(f"\n[bold]{confirmed} confirmed"
                  + (f", {propagated} more resolved by propagation"
                     if propagated else "") + ".[/bold]")
    # Loop 2: retrain the fallback model on the grown label set
    if confirmed and SKLEARN_AVAILABLE:
        if Pipeline(store).retrain_fallback():
            console.print("[dim]Fallback model retrained on your labels.[/dim]")


# --------------------------------------------------------------- reclassify
@app.command()
def reclassify():
    """Re-run the pipeline over everything you haven't confirmed, using your
    current memory, dictionary, and retrained model.

    Use after: a bulk backfill review session, a dictionary update, or a
    category change. Confirmed transactions are never touched.
    """
    store = _store()
    txns = [t for t in store.all_transactions() if t.status != Status.CONFIRMED]
    if not txns:
        console.print("Nothing unconfirmed — all clean.")
        return
    # reset provisional state so stale suggestions don't stick
    for t in txns:
        if not t.is_transfer:
            t.category, t.confidence, t.stage = "", 0.0, Stage.NONE
            t.subcategory = ""
            t.status = Status.UNRESOLVED
    stats = Pipeline(store).run(txns)
    for t in txns:
        store.update_transaction(t)
    resolved = stats.total - stats.by_stage.get("none", 0)
    console.print(f"[green]{resolved}/{stats.total} unconfirmed transactions "
                  f"now resolved.[/green]")
    _print_stage_table(stats.by_stage)


# ------------------------------------------------------------------- report
@app.command()
def report(month: str = typer.Option("", help="YYYY-MM, default: all"),
           by_month: bool = typer.Option(False, "--by-month",
                                         help="Month-on-month trend table"),
           as_json: bool = typer.Option(False, "--json",
                                        help="Machine-readable output")):
    """Spending by category — single period or month-on-month trend."""
    store = _store()
    txns = [t for t in store.all_transactions()
            if not t.is_transfer and t.direction.value == "debit"]
    if month:
        txns = [t for t in txns if t.date.isoformat().startswith(month)]
    if not txns:
        console.print("No transactions found.")
        return
    currency = store.get_config("currency", "INR")

    if as_json:
        cell: dict = defaultdict(lambda: defaultdict(float))
        for t in txns:
            cell[t.date.isoformat()[:7]][t.category or "(uncategorized)"] \
                += t.amount
        if by_month:
            payload = {"currency": currency,
                       "months": {m: dict(c) for m, c in sorted(cell.items())}}
        else:
            totals: dict = defaultdict(float)
            for c in cell.values():
                for cat, v in c.items():
                    totals[cat] += v
            payload = {"currency": currency, "period": month or "all",
                       "categories": dict(sorted(totals.items(),
                                                 key=lambda x: -x[1]))}
        print(json.dumps(payload, indent=2))
        return

    if by_month:
        months = sorted({t.date.isoformat()[:7] for t in txns})
        cat_totals: dict[str, float] = defaultdict(float)
        cell: dict[tuple[str, str], float] = defaultdict(float)
        for t in txns:
            cat = t.category or "(uncat.)"
            cat_totals[cat] += t.amount
            cell[(t.date.isoformat()[:7], cat)] += t.amount
        top = [c for c, _ in sorted(cat_totals.items(), key=lambda x: -x[1])[:6]]
        table = Table(title=f"Month on month ({currency})")
        table.add_column("Month")
        for c in top:
            table.add_column(c, justify="right")
        table.add_column("Other", justify="right")
        table.add_column("[bold]Total[/bold]", justify="right")
        for m in months:
            row_total = sum(v for (mm, _), v in cell.items() if mm == m)
            top_sum = sum(cell.get((m, c), 0) for c in top)
            table.add_row(
                m, *[f"{cell.get((m, c), 0):,.0f}" for c in top],
                f"{row_total - top_sum:,.0f}", f"[bold]{row_total:,.0f}[/bold]",
            )
        console.print(table)
        return
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for t in txns:
        cat = t.category or "(uncategorized)"
        totals[cat] += t.amount
        counts[cat] += 1
    grand = sum(totals.values())
    table = Table(title=f"Spending {'in ' + month if month else '(all time)'}")
    table.add_column("Category")
    table.add_column("Txns", justify="right")
    table.add_column(f"Total ({currency})", justify="right")
    table.add_column("Share", justify="right")
    for cat, total in sorted(totals.items(), key=lambda x: -x[1]):
        table.add_row(cat, str(counts[cat]), f"{total:,.2f}",
                      f"{100 * total / grand:.1f}%")
    table.add_row("[bold]Total[/bold]", str(len(txns)),
                  f"[bold]{grand:,.2f}[/bold]", "")
    console.print(table)


# -------------------------------------------------------------------- stats
@app.command()
def stats(as_json: bool = typer.Option(False, "--json")):
    """Pipeline health: coverage by stage, measured accuracy per stage."""
    store = _store()
    txns = store.all_transactions()
    if not txns:
        console.print("No data yet — run munim import first.")
        return
    by_stage: dict[str, int] = defaultdict(int)
    for t in txns:
        by_stage[t.stage.value] += 1
    if as_json:
        acc = {r["stage"]: {"n": r["n"], "accuracy": r["accuracy"]}
               for r in store.stage_accuracy()}
        print(json.dumps({
            "total": len(txns),
            "by_stage": dict(by_stage),
            "measured_accuracy": acc,
            "memory_rules": len(store.memory_rules("merchant"))
            + len(store.memory_rules("payee")),
        }, indent=2))
        return
    _print_stage_table(by_stage, total=len(txns))

    rows = store.stage_accuracy()
    if rows:
        table = Table(title="Measured accuracy (from your corrections — Loop 3)")
        table.add_column("Stage")
        table.add_column("Predictions", justify="right")
        table.add_column("Accuracy", justify="right")
        for r in rows:
            table.add_row(r["stage"], str(r["n"]), f"{r['accuracy']:.1%}")
        console.print(table)
    mem = len(store.memory_rules("merchant")) + len(store.memory_rules("payee"))
    console.print(f"\nMemory rules learned from you: [bold]{mem}[/bold]")


def _print_stage_table(by_stage: dict, total: int | None = None) -> None:
    total = total or sum(by_stage.values())
    if not total:
        return
    table = Table(title="Resolution by stage")
    table.add_column("Stage")
    table.add_column("Count", justify="right")
    table.add_column("Share", justify="right")
    order = ["structural", "memory_exact", "memory_fuzzy", "dictionary",
             "purpose", "fallback", "none"]
    labels = {"structural": "Structural (transfers etc.)",
              "memory_exact": "Memory — exact",
              "memory_fuzzy": "Memory — fuzzy",
              "dictionary": "Community dictionary",
              "purpose": "Purpose keyword (narration text)",
              "fallback": "Fallback classifier",
              "none": "Unresolved (review queue)"}
    for key in order:
        n = by_stage.get(key, 0)
        if n:
            table.add_row(labels[key], str(n), f"{100 * n / total:.1f}%")
    console.print(table)


# ---------------------------------------------------------------------- web
@app.command()
def web(port: int = typer.Option(8646, help="Local port"),
        no_browser: bool = typer.Option(False, "--no-browser")):
    """Open the local one-page ledger UI: review, transactions, categories,
    rules, contribute. Binds 127.0.0.1 only; nothing leaves your machine.
    This is a UI over the SQLite data contract — apps should integrate via
    the contract and classify/learn, not these private endpoints."""
    from .web import run_server
    run_server(_store(), port=port, open_browser=not no_browser)


# ----------------------------------------------------------------- classify
@app.command()
def classify(store_results: bool = typer.Option(False, "--store",
                                                help="Also persist to the DB")):
    """Stateless classification for host apps: JSONL in on stdin, JSONL out.

    Input, one object per line:
      {"date": "2026-06-01", "amount": 340.0, "direction": "debit",
       "description": "UPI-SWIGGY8102@okaxis-513324498812",
       "account": "hdfc", "currency": "INR"}
    Output adds: merchant_norm, payee_handle, category, confidence, stage,
    status, is_transfer, is_recurring. Uses your memory and dictionary but
    writes nothing unless --store. This is the embedding API — see
    docs/embedding.md.
    """
    import sys
    store = _store()
    txns = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        txns.append(Transaction(
            date=d["date"], amount=abs(float(d["amount"])),
            direction=d.get("direction", "debit"),
            description_raw=d.get("description", d.get("description_raw", "")),
            account=d.get("account", "default"),
            currency=d.get("currency", store.get_config("currency", "INR")),
        ))
    if not txns:
        console.print("[red]No input on stdin.[/red]", file=None)
        raise typer.Exit(1)
    Pipeline(store).run(txns)
    if store_results:
        store.upsert_transactions(txns)
    for t in txns:
        d = t.model_dump()
        d["date"] = t.date.isoformat()
        print(json.dumps(d, ensure_ascii=False))


# -------------------------------------------------------------------- learn
@app.command()
def learn(pattern: str, category: str,
          payee: bool = typer.Option(False, "--payee",
                                     help="Pattern is a person, not a merchant"),
          subcategory: str = typer.Option(
              "", "--subcategory",
              help="Optional finer-grained head under category, e.g. Alcohol under Groceries"),
          propagate: bool = typer.Option(True,
                                         help="Apply to stored unconfirmed txns")):
    """Write one confirmed rule to memory — the feedback channel for host
    apps. When a user confirms a category in YOUR review UI, call this so
    the engine learns. Pure memory write; no transaction required to exist.
    """
    store = _store()
    cats = store.get_config("categories", DEFAULT_CATEGORIES)
    if category not in cats:
        console.print(f"[red]{category} is not in the taxonomy "
                      f"(munim categories list).[/red]")
        raise typer.Exit(1)
    if subcategory:
        subcats = store.get_config("subcategories", {}) or {}
        if subcategory not in subcats.get(category, []):
            console.print(
                f"[red]{subcategory} is not a subcategory of {category} "
                f"(munim categories subcategories list {category}).[/red]")
            raise typer.Exit(1)
    kind = "payee" if payee else "merchant"
    pattern = pattern.upper().strip()
    store.remember(pattern, category, kind=kind, subcategory=subcategory)
    n = store.propagate(pattern, category, kind, subcategory=subcategory) \
        if propagate else 0
    console.print(f"[green]Learned: {pattern} → {category}"
                  + (f" / {subcategory}" if subcategory else "") + "[/green]"
                  + (f" ({n} stored transactions updated)" if n else ""))
    if subcategory:
        n_sub = store.apply_subcategory(pattern, subcategory, kind)
        console.print(f"[dim]Subcategory applied to {n_sub} matching "
                      "transactions (including already-confirmed ones).[/dim]")


# --------------------------------------------------------------- categories
cat_app = typer.Typer(help="Manage your category taxonomy.", no_args_is_help=True)
app.add_typer(cat_app, name="categories")


@cat_app.command("list")
def categories_list():
    """Show your current categories and how much each has been used."""
    store = _store()
    cats = store.get_config("categories", DEFAULT_CATEGORIES)
    usage = {r["category"]: r["n"] for r in store.db.execute(
        "SELECT category, COUNT(*) AS n FROM transactions "
        "WHERE category != '' GROUP BY category")}
    table = Table(title="Categories")
    table.add_column("Name")
    table.add_column("Transactions", justify="right")
    for c in cats:
        table.add_row(c, str(usage.get(c, 0)))
    orphans = set(usage) - set(cats)
    for c in sorted(orphans):
        table.add_row(f"[yellow]{c} (not in taxonomy)[/yellow]", str(usage[c]))
    console.print(table)


@cat_app.command("add")
def categories_add(name: str,
                   path: str = typer.Option("", help="Ledger path, e.g. Expenses:Food:Snacks"),
                   force: bool = typer.Option(False, "--force")):
    """Add a new category (max 20 — labeling consistency is the product)."""
    from .tree import MAX_LEAVES, valid_path, ROOTS
    store = _store()
    cats = store.get_config("categories", DEFAULT_CATEGORIES)
    if name in cats:
        console.print(f"[yellow]{name} already exists.[/yellow]")
        raise typer.Exit(1)
    if len(cats) >= MAX_LEAVES and not force:
        console.print(f"[red]You already have {len(cats)} categories — the "
                      f"limit is {MAX_LEAVES}.[/red] More heads means less "
                      "consistent labeling, which poisons memory and training "
                      "data. Merge something first (munim categories remove "
                      "--reassign-to), or --force if you accept the tradeoff.")
        raise typer.Exit(1)
    if path and not valid_path(path):
        console.print(f"[red]Path must start with one of: {', '.join(ROOTS)}[/red]")
        raise typer.Exit(1)
    tree = store.get_config("category_tree", {}) or {}
    tree[name] = path or f"Expenses:{name}"
    store.set_config("category_tree", tree)
    cats.append(name)
    store.set_config("categories", cats)
    console.print(f"[green]Added {name}.[/green] It will appear in munim review.")


@cat_app.command("rename")
def categories_rename(old: str, new: str):
    """Rename a category everywhere: taxonomy, memory, past transactions.

    Also installs an alias so community-dictionary hits (which use the
    standard taxonomy) map to your name from now on.
    """
    store = _store()
    cats = store.get_config("categories", DEFAULT_CATEGORIES)
    if old not in cats:
        console.print(f"[red]{old} is not in your taxonomy.[/red]")
        raise typer.Exit(1)
    cats = [new if c == old else c for c in cats]
    store.set_config("categories", cats)
    # Cascade: everything you've taught the system follows the rename
    n_mem = store.db.execute(
        "UPDATE memory SET category=? WHERE category=?", (new, old)).rowcount
    n_txn = store.db.execute(
        "UPDATE transactions SET category=? WHERE category=?", (new, old)).rowcount
    store.db.execute(
        "UPDATE corrections SET final_category=? WHERE final_category=?",
        (new, old))
    store.db.commit()
    # Subcategories are keyed by category name — move the entry along with
    # the rename (renaming, not merging, so existing subcategory VALUES on
    # transactions/memory rows are still valid and untouched above).
    subcats = store.get_config("subcategories", {}) or {}
    if old in subcats:
        old_list = subcats.pop(old)
        existing = subcats.get(new, [])
        subcats[new] = existing + [s for s in old_list if s not in existing]
        store.set_config("subcategories", subcats)
    # Alias: future dictionary hits for the standard name emit your name.
    aliases = store.get_config("category_aliases", {})
    aliases[old] = new
    # Collapse chains (Dining->Food, then Food->Meals => Dining->Meals)
    aliases = {k: (new if v == old else v) for k, v in aliases.items()}
    store.set_config("category_aliases", aliases)
    console.print(f"[green]Renamed {old} → {new}[/green]: "
                  f"{n_txn} transactions, {n_mem} memory rules updated. "
                  f"Dictionary hits will use [bold]{new}[/bold] from now on.")


@cat_app.command("remove")
def categories_remove(
    name: str,
    reassign_to: str = typer.Option("Other", help="Move existing txns here"),
):
    """Remove a category. Existing transactions are reassigned, not lost."""
    store = _store()
    cats = store.get_config("categories", DEFAULT_CATEGORIES)
    if name not in cats:
        console.print(f"[red]{name} is not in your taxonomy.[/red]")
        raise typer.Exit(1)
    if name == "Transfers":
        console.print("[red]Transfers is structural — it can be renamed "
                      "but not removed (double-counting protection).[/red]")
        raise typer.Exit(1)
    if reassign_to not in cats or reassign_to == name:
        console.print(f"[red]Invalid reassignment target: {reassign_to}[/red]")
        raise typer.Exit(1)
    # The removed category's subcategory list was only ever valid under
    # IT, not necessarily under reassign_to — clear subcategory on every
    # row being moved, on both tables.
    n = store.db.execute(
        "UPDATE transactions SET category=?, subcategory='' WHERE category=?",
        (reassign_to, name)).rowcount
    store.db.execute("UPDATE memory SET category=?, subcategory='' WHERE category=?",
                     (reassign_to, name))
    store.db.commit()
    cats.remove(name)
    store.set_config("categories", cats)
    subcats = store.get_config("subcategories", {}) or {}
    if name in subcats:
        subcats.pop(name)
        store.set_config("subcategories", subcats)
    aliases = store.get_config("category_aliases", {})
    aliases[name] = reassign_to
    store.set_config("category_aliases", aliases)
    console.print(f"[green]Removed {name}[/green] — {n} transactions and its "
                  f"memory rules moved to [bold]{reassign_to}[/bold].")


@cat_app.command("tree")
def categories_tree():
    """Show the display tree: flat leaves mapped under the five roots
    (Assets, Liabilities, Equity, Income, Expenses)."""
    from .tree import get_tree, root_of
    store = _store()
    tree = get_tree(store)
    table = Table(title="Category tree (display mapping — the engine stays flat)")
    table.add_column("Leaf")
    table.add_column("Ledger path")
    table.add_column("Root")
    for leaf, path in sorted(tree.items(), key=lambda x: (x[1], x[0])):
        table.add_row(leaf, path, root_of(path))
    console.print(table)


@cat_app.command("map")
def categories_map(leaf: str, path: str):
    """Map a leaf to a ledger path, e.g.: munim categories map Fuel Expenses:Transport:Fuel"""
    from .tree import valid_path, ROOTS
    store = _store()
    cats = store.get_config("categories", DEFAULT_CATEGORIES)
    if leaf not in cats:
        console.print(f"[red]{leaf} is not a category (munim categories list).[/red]")
        raise typer.Exit(1)
    if not valid_path(path):
        console.print(f"[red]Path must start with one of: {', '.join(ROOTS)}[/red]")
        raise typer.Exit(1)
    tree = store.get_config("category_tree", {}) or {}
    tree[leaf] = path
    store.set_config("category_tree", tree)
    console.print(f"[green]{leaf} → {path}[/green] (exports and dashboard "
                  "use this; classification stays flat)")


subcat_app = typer.Typer(help="Manage subcategories under a category head.",
                         no_args_is_help=True)
cat_app.add_typer(subcat_app, name="subcategories")


@subcat_app.command("add")
def subcategories_add(parent: str, name: str,
                      force: bool = typer.Option(False, "--force")):
    """Add a subcategory under an existing category, e.g.:
    munim categories subcategories add Groceries Alcohol"""
    from .tree import MAX_SUBCATEGORIES_PER_PARENT
    store = _store()
    cats = store.get_config("categories", DEFAULT_CATEGORIES)
    if parent not in cats:
        console.print(f"[red]{parent} is not a category "
                      f"(munim categories list).[/red]")
        raise typer.Exit(1)
    subcats = store.get_config("subcategories", {}) or {}
    existing = subcats.get(parent, [])
    if name in existing:
        console.print(f"[yellow]{parent}:{name} already exists.[/yellow]")
        raise typer.Exit(1)
    if len(existing) >= MAX_SUBCATEGORIES_PER_PARENT and not force:
        console.print(
            f"[red]{parent} already has {len(existing)} subcategories — "
            f"the limit is {MAX_SUBCATEGORIES_PER_PARENT} per head.[/red] "
            "--force if you accept the tradeoff.")
        raise typer.Exit(1)
    subcats[parent] = existing + [name]
    store.set_config("subcategories", subcats)
    console.print(f"[green]Added {parent}:{name}.[/green] Teach it with: "
                  f"munim learn <pattern> {parent} --subcategory {name}")


@subcat_app.command("list")
def subcategories_list(
    parent: str = typer.Argument(None, help="Show one head's subcategories only"),
):
    """Show subcategories and how much each has been used."""
    store = _store()
    subcats = store.get_config("subcategories", {}) or {}
    usage = {(r["category"], r["subcategory"]): r["n"] for r in store.db.execute(
        "SELECT category, subcategory, COUNT(*) AS n FROM transactions "
        "WHERE subcategory != '' GROUP BY category, subcategory")}
    items = subcats.items() if not parent else [(parent, subcats.get(parent, []))]
    if not any(names for _, names in items):
        console.print("[dim]No subcategories yet — "
                      "munim categories subcategories add <head> <name>[/dim]")
        return
    table = Table(title="Subcategories")
    table.add_column("Head")
    table.add_column("Subcategory")
    table.add_column("Transactions", justify="right")
    for head, names in items:
        for name in names:
            table.add_row(head, name, str(usage.get((head, name), 0)))
    console.print(table)


# ----------------------------------------------------------------- accounts
acct_app = typer.Typer(help="Manage account types.", no_args_is_help=True)
app.add_typer(acct_app, name="accounts")


@acct_app.command("list")
def accounts_list():
    """Accounts and their root type (Assets or Liabilities)."""
    from .tree import account_root
    store = _store()
    rows = store.db.execute(
        "SELECT account, COUNT(*) AS n FROM transactions GROUP BY account").fetchall()
    table = Table(title="Accounts")
    table.add_column("Account")
    table.add_column("Type")
    table.add_column("Entries", justify="right")
    for r in rows:
        table.add_row(r["account"], account_root(store, r["account"]), str(r["n"]))
    console.print(table)


@acct_app.command("type")
def accounts_type(account: str, root: str):
    """Set an account's root: Assets (bank/wallet) or Liabilities (credit
    card, loan). Exports and the dashboard use this."""
    if root not in ("Assets", "Liabilities"):
        console.print("[red]Account type must be Assets or Liabilities.[/red]")
        raise typer.Exit(1)
    store = _store()
    types = store.get_config("account_types", {}) or {}
    types[account] = root
    store.set_config("account_types", types)
    console.print(f"[green]{account} → {root}[/green]")


# ------------------------------------------------------------------- export
@app.command()
def export(
    out: Path = typer.Option(None, help="Output file (default: stdout-friendly name)"),
    fmt: str = typer.Option("csv", "--format",
                            help="csv | jsonl | ledger | firefly"),
):
    """Hand your categorized data to the tools that do budgeting and trends.

    csv: flat file · jsonl: pipelines/notebooks · ledger: plain-text
    accounting · firefly: Firefly III Data Importer.
    """
    from . import export_formats as ef
    store = _store()
    txns = store.all_transactions()
    if not txns:
        console.print("Nothing to export.")
        raise typer.Exit(1)
    if fmt == "jsonl":
        out = out or Path("munim-export.jsonl")
        out.write_text(ef.to_jsonl(txns), encoding="utf-8")
    elif fmt == "ledger":
        from .tree import get_tree
        out = out or Path("munim-export.ledger")
        out.write_text(ef.to_ledger(
            txns, tree=get_tree(store),
            account_types=store.get_config("account_types", {}) or {},
        ), encoding="utf-8")
    elif fmt == "firefly":
        out = out or Path("munim-firefly.csv")
        out.write_text(ef.to_firefly_csv(txns), encoding="utf-8")
    elif fmt == "csv":
        out = out or Path("munim-export.csv")
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv_module.writer(f)
            w.writerow(["date", "amount", "currency", "direction", "category",
                        "merchant", "account", "recurring", "transfer",
                        "status", "classified_by", "description_raw"])
            for t in txns:
                w.writerow([t.date, t.amount, t.currency, t.direction.value,
                            t.category, t.merchant_norm or t.payee_handle,
                            t.account, t.is_recurring, t.is_transfer,
                            t.status.value, t.stage.value, t.description_raw])
    else:
        console.print(f"[red]Unknown format: {fmt}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Exported {len(txns)} transactions to {out} "
                  f"({fmt})[/green]")


# ------------------------------------------------------------------- doctor
@app.command()
def doctor(as_json: bool = typer.Option(False, "--json")):
    """Data-quality checks: month gaps, missing accounts, dedup risk,
    review backlog. Run after every backfill."""
    from .doctor import run_checks
    report = run_checks(_store())
    if as_json:
        print(json.dumps(report, indent=2))
        return
    for c in report["checks"]:
        mark = "[green]✓[/green]" if c["ok"] else "[red]✗[/red]"
        console.print(f"{mark} [bold]{c['name']}[/bold]")
        details = c["detail"] if isinstance(c["detail"], list) else [c["detail"]]
        for line in details:
            console.print(f"    {line}")
    if not report["total"]:
        console.print("\nNo transactions yet — run munim import, then "
                      "doctor again for the full checks.")
        return
    console.print("\n[green]All checks passed.[/green]" if report["ok"]
                  else "\n[yellow]Issues found — fix before trusting "
                       "the trends.[/yellow]")


# --------------------------------------------------------------- contribute
@app.command()
def contribute(out: Path = typer.Option(Path("contrib"),
                                        help="Output directory")):
    """Generate a PR-ready, anonymized dictionary contribution from your
    confirmed labels. Merchant patterns only — never people, amounts,
    dates, or accounts. Review the file before submitting."""
    from .contribute import build_bundle
    result = build_bundle(_store(), out)
    if result["patterns"] == 0:
        console.print("No new patterns to contribute yet — everything you've "
                      "confirmed is already in the community dictionary.")
        return
    console.print(f"[green]{result['patterns']} candidate patterns[/green] "
                  f"across {result['categories']} categories → "
                  f"[bold]{result['file']}[/bold]")
    console.print(f"[dim]{result['skipped_known_or_unsafe']} skipped "
                  f"(already known, or too short/generic to share).[/dim]")
    console.print("Review the file, prune anything local-only, then append "
                  "to data/dictionary/ and open a PR.")


# ------------------------------------------------------------------ relabel
@app.command()
def relabel(pattern: str, category: str):
    """Non-interactive correction: re-map a merchant/payee everywhere.
    Overrides previous confirmations — this is the undo for a wrong review."""
    store = _store()
    cats = store.get_config("categories", DEFAULT_CATEGORIES)
    if category not in cats:
        console.print(f"[red]{category} is not in your taxonomy "
                      f"(munim categories list).[/red]")
        raise typer.Exit(1)
    pattern = pattern.upper().strip()
    kinds = store.db.execute(
        "SELECT kind FROM memory WHERE pattern=?", (pattern,)).fetchall()
    kind = kinds[0]["kind"] if kinds else "merchant"
    # A subcategory already on file survives only if `category` matches
    # what memory has for this pattern — otherwise it no longer applies.
    sub = store.existing_subcategory(pattern, kind, category)
    store.remember(pattern, category, kind=kind, subcategory=sub)
    col = "payee_handle" if kind == "payee" else "merchant_norm"
    # is_transfer must track the category, not just the structural
    # auto-detector — see the same note in store.propagate().
    is_transfer = 1 if category == "Transfers" else 0
    n = store.db.execute(
        f"UPDATE transactions SET category=?, subcategory=?, status='confirmed', "
        f"stage='user', confidence=1.0, is_transfer=? WHERE {col}=?",
        (category, sub, is_transfer, pattern)).rowcount
    store.db.commit()
    console.print(f"[green]{pattern} → {category}[/green]: {n} transactions "
                  f"updated, memory rule replaced.")


# --------------------------------------------------------------------- eval
@app.command("eval")
def run_eval(fixture: Path = typer.Option(None, help="Labeled fixture CSV")):
    """Run the benchmark — every accuracy claim must be reproducible."""
    from eval.run_eval import evaluate  # noqa: local import, dev-time tool
    evaluate(fixture)


if __name__ == "__main__":
    app()
