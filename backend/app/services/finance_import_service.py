"""Import of the monthly P&L workbook (.xlsm/.xlsx) into Финансы -> Расходы
(product ask, 2026-10-26). The sheet looks like this (see PnL/ЧП Новая.xlsm):

- row 1: the workshops - a merged header per workshop ("Каховка Кузов",
  "Каховка Слесарка", "Солнцево Кузов"), three columns each: "В том числе"
  (free text), "Доход", "Расход";
- row 2: those column names;
- the rows below: one cost item per row, its name in column B and the amount
  in each workshop's "Расход" column. The revenue rows have only "Доход" (the
  system computes revenue itself), so they bring nothing; rows marked "V" in
  column C are a breakdown of the row above (already inside its figure, and
  excluded from the sheet's own totals); the table ends at the "Итого" row.

The month is chosen by the user, not read from the file. NOTHING is created:
a name that is not in the cost-item directory is not loaded and is listed in
the report (product ask, 2026-10-26); a workshop column that matches no
workshop is reported and skipped; an inactive item is skipped (its cells are
locked).
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.workshop import Workshop
from app.services import finance_service
from app.services.finance_service import FinanceInvalid

MAX_FILE_BYTES = 8 * 1024 * 1024
MONTH_NAMES = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]
_CENT = Decimal("0.01")


def _norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold().replace("ё", "е")


@dataclass
class ParsedGroup:
    label: str
    column: int  # the "Расход" column (1-based)


@dataclass
class ParsedRow:
    name: str
    row: int
    values: dict[int, Decimal]  # "Расход" column -> amount


@dataclass
class ParsedSheet:
    title: str
    groups: list[ParsedGroup]
    rows: list[ParsedRow]
    warnings: list[str] = field(default_factory=list)


def _to_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value)).quantize(_CENT)
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text).quantize(_CENT)
    except InvalidOperation:
        return None


def parse_workbook(content: bytes, year: int, month: int) -> ParsedSheet:
    if len(content) > MAX_FILE_BYTES:
        raise FinanceInvalid("Файл слишком большой")
    try:
        workbook = load_workbook(io.BytesIO(content), data_only=True, keep_vba=False)
    except Exception as exc:  # not a workbook at all / corrupt
        raise FinanceInvalid("Не удалось прочитать файл: нужен Excel (.xlsm или .xlsx)") from exc

    sheets = [ws for ws in workbook.worksheets if ws.sheet_state == "visible"] or list(
        workbook.worksheets
    )
    wanted = f"{MONTH_NAMES[month - 1]} {year}"
    sheet = next((ws for ws in sheets if _norm(ws.title) == wanted), sheets[0])

    warnings: list[str] = []
    if _norm(sheet.title) != wanted:
        warnings.append(
            f"Лист «{sheet.title}» не совпадает с выбранным месяцем — загружается, как указано вами"
        )

    # workshop groups: a value in row 1, its "Расход" column in row 2 within the
    # group's merged span (three columns when there is no merge)
    spans: dict[int, int] = {}
    for merged in sheet.merged_cells.ranges:
        if merged.min_row == 1:
            spans[merged.min_col] = merged.max_col
    groups: list[ParsedGroup] = []
    for cell in sheet[1]:
        if cell.value is None or not str(cell.value).strip():
            continue
        last = spans.get(cell.column, cell.column + 2)
        column = next(
            (
                c
                for c in range(cell.column, last + 1)
                if _norm(sheet.cell(row=2, column=c).value) == "расход"
            ),
            None,
        )
        if column is not None and cell.column > 3:  # B:C is the "Статья ..." header
            groups.append(ParsedGroup(label=str(cell.value).strip(), column=column))
    if not groups:
        raise FinanceInvalid("В файле не найдены колонки цехов с «Расход» (строки 1–2)")

    rows: list[ParsedRow] = []
    for row_number in range(3, sheet.max_row + 1):
        name = str(sheet.cell(row=row_number, column=2).value or "").strip()
        marker = str(sheet.cell(row=row_number, column=3).value or "").strip().upper()
        if _norm(name) == "итого":
            break
        if not name or marker == "V":
            continue
        values: dict[int, Decimal] = {}
        for group in groups:
            raw = sheet.cell(row=row_number, column=group.column).value
            amount = _to_decimal(raw)
            if amount is None:
                continue
            if amount < 0:
                warnings.append(f"Строка {row_number} «{name}»: отрицательное значение пропущено")
                continue
            values[group.column] = amount
        if values:
            rows.append(ParsedRow(name=re.sub(r"\s+", " ", name), row=row_number, values=values))
    return ParsedSheet(title=sheet.title, groups=groups, rows=rows, warnings=warnings)


def _match_workshop(label: str, workshops: list[tuple[Workshop, str]]) -> Workshop | None:
    """ "Каховка Кузов" / "Каховка Слесарка" -> the workshop whose department
    name and workshop type both appear (by stem) in the header."""
    text = _norm(label)
    for workshop, department_name in workshops:
        stem = _norm(workshop.workshop_type)[:5]
        if _norm(department_name) in text and stem and stem in text:
            return workshop
    return None


def run_import(db: Session, content: bytes, *, year: int, month: int, apply: bool) -> dict:
    """Parses the file and reports what it would do; with apply=True does it
    (one transaction: new items, then every cell)."""
    parsed = parse_workbook(content, year, month)

    workshops = [
        (workshop, department_name)
        for workshop, department_name in db.execute(
            select(Workshop, Department.name).join(
                Department, Department.id == Workshop.department_id
            )
        ).all()
    ]
    column_workshop: dict[int, Workshop] = {}
    group_report = []
    for group in parsed.groups:
        workshop = _match_workshop(group.label, workshops)
        if workshop is not None:
            column_workshop[group.column] = workshop
        label = None
        if workshop is not None:
            department_name = next(d for w, d in workshops if w.id == workshop.id)
            label = f"{department_name} — {workshop.workshop_type}"
        group_report.append({"file_label": group.label, "workshop": label})

    items = {_norm(i.name): i for i in finance_service.list_cost_items(db)}
    missing_names: list[str] = []
    inactive: list[str] = []
    plan: list[tuple[uuid.UUID, Workshop, Decimal]] = []
    for row in parsed.rows:
        key = _norm(row.name)
        item = items.get(key)
        if item is None:
            if row.name not in missing_names:
                missing_names.append(row.name)
            continue
        if not item.is_active:
            inactive.append(row.name)
            continue
        for column, amount in row.values.items():
            workshop = column_workshop.get(column)
            if workshop is not None:
                plan.append((item.id, workshop, amount))

    total = sum((amount for _, _, amount in plan), Decimal("0"))
    report = {
        "applied": False,
        "year": year,
        "month": month,
        "sheet": parsed.title,
        "workshops": group_report,
        "rows": len(parsed.rows),
        "cells": len(plan),
        "total": total,
        "missing_items": missing_names,
        "skipped_inactive": inactive,
        "warnings": parsed.warnings
        + [
            f"Колонка «{g['file_label']}» не сопоставлена с цехом — пропущена"
            for g in group_report
            if g["workshop"] is None
        ],
    }
    if not apply:
        return report
    if not plan:
        raise FinanceInvalid("В файле нет значений, которые можно загрузить")

    try:
        for item_id, workshop, amount in plan:
            finance_service.set_cell(
                db,
                cost_item_id=item_id,
                workshop_id=workshop.id,
                year=year,
                month=month,
                amount=amount,
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    report["applied"] = True
    return report
