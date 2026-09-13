import Link from "next/link";
import { notFound } from "next/navigation";

import { WorkOrderLineTabs } from "@/components/WorkOrderLineTabs";
import { getWorkOrder } from "@/lib/backend-api";

// See app/work-orders/page.tsx for why this is required.
export const dynamic = "force-dynamic";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function formatAmount(amount: string): string {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(amount)) + " ₽";
}

export default async function WorkOrderDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let workOrder;
  let error: string | null = null;
  let missing = false;

  try {
    workOrder = await getWorkOrder(id);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    if (message.includes("404")) {
      missing = true;
    } else {
      error = message;
    }
  }

  if (missing) {
    notFound();
  }

  return (
    <div>
      <p className="detail-back">
        <Link href="/work-orders">← К списку заказ-нарядов</Link>
      </p>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {workOrder && (
        <>
          <h1>Заказ-наряд {workOrder.external_number}</h1>

          <div className="card detail-header">
            <div className="detail-field">
              <span className="detail-label">Дата</span>
              <span>{formatDate(workOrder.document_date)}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Контрагент</span>
              <span>{workOrder.customer_name || "—"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Автомобиль</span>
              <span>{workOrder.vehicle_description || "—"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Статус</span>
              <span>{workOrder.status || "—"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Подразделение</span>
              <span>{workOrder.department || "—"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Сумма</span>
              <span>{formatAmount(workOrder.amount)}</span>
            </div>
          </div>

          <div className="card">
            <WorkOrderLineTabs labor={workOrder.labor} parts={workOrder.parts} />
          </div>
        </>
      )}
    </div>
  );
}
