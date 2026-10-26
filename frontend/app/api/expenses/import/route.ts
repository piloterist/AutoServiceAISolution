// Финансы -> Расходы -> Импорт: receives the P&L workbook from the browser and
// hands it to the backend (see backend services/finance_import_service.py).
import { NextRequest, NextResponse } from "next/server";

import { importExpensesFile } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";

export async function POST(request: NextRequest) {
  try {
    const form = await request.formData();
    const file = form.get("file");
    const year = Number(form.get("year"));
    const month = Number(form.get("month"));
    if (!(file instanceof File) || !year || !month) {
      return NextResponse.json({ error: "Выберите файл и месяц" }, { status: 400 });
    }
    const report = await importExpensesFile({
      year,
      month,
      dryRun: form.get("dry_run") !== "false",
      content: await file.arrayBuffer(),
    });
    return NextResponse.json(report);
  } catch (err) {
    return cashErrorResponse(err);
  }
}
