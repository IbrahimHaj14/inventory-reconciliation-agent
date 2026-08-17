import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from reconciler.agent import run_agent
from reconciler.config import settings
from reconciler.models import ReconciliationReport
from reconciler.narrator import render_narrative
from reconciler.sources.simulated import load_scenario

app = typer.Typer(help="Deterministic multi-source inventory reconciliation.")


@app.callback()
def main() -> None:
    """Reconcile inventory from deterministic scenario inputs."""


def _decision_table(report: ReconciliationReport) -> Table:
    table = Table(title="Decision Log")
    table.add_column("Step", justify="right")
    table.add_column("Decision")
    table.add_column("Subject")
    table.add_column("Rationale")
    for record in report.decision_log:
        table.add_row(
            str(record.step),
            record.decision.value,
            record.subject,
            record.rationale,
        )
    return table


def _health_table(report: ReconciliationReport) -> Table:
    table = Table(title="Source Health")
    table.add_column("Source")
    table.add_column("Trust", justify="right")
    table.add_column("Freshness", justify="right")
    table.add_column("Latency", justify="right")
    table.add_column("Reliability", justify="right")
    table.add_column("Reason")
    for health in report.source_health:
        table.add_row(
            health.source.value,
            f"{health.trust:.3f}",
            f"{health.freshness:.3f}",
            f"{health.latency_health:.3f}",
            f"{health.reliability:.3f}",
            health.reason,
        )
    return table


def _sku_table(report: ReconciliationReport) -> Table:
    table = Table(title="SKU Results")
    table.add_column("SKU")
    table.add_column("Value")
    table.add_column("Status")
    table.add_column("Confidence", justify="right")
    for sku in report.skus:
        value = "REFUSED" if sku.reconciled_quantity is None else str(sku.reconciled_quantity)
        table.add_row(
            sku.sku,
            value,
            sku.status.value,
            f"{sku.confidence:.3f}",
        )
    return table


@app.command("run")
def run_scenario(
    scenario: Annotated[Path, typer.Argument(help="Scenario YAML file to run.")],
    json_path: Annotated[
        Path,
        typer.Option("--json", help="Path for the machine-auditable JSON report."),
    ] = Path("report.json"),
) -> None:
    """Run a scenario and emit both operator-readable and JSON reports."""
    spec = load_scenario(str(scenario))
    report = asyncio.run(run_agent(spec, settings, datetime.now(UTC)))

    console = Console()
    console.print(_decision_table(report))
    console.print(_health_table(report))
    console.print(_sku_table(report))
    console.print(render_narrative(report))

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"Report written to {json_path}")
