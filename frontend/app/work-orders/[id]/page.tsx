import Link from "next/link";
import { notFound } from "next/navigation";

import { WorkOrderLineTabs } from "@/components/WorkOrderLineTabs";
import { getWorkOrder } from "@/lib/backend-api";

// Must never be statically prerendered: if the backend happens to be
// reachable at build time, Next.js could otherwise freeze this page with
// build-time data that never updates after deploy until the next rebuild.
export const dynamic = "force-dynamic";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function formatAmount(amount: string | null): string {
  if (amount === null) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(amount)) + " ₽";
}

function formatPercent(percent: string | null): string {
  if (percent === null || Number(percent) === 0) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(percent)) + "%";
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
              <span className="detail-label">Дата создания</span>
              <span>{workOrder.created_date ? formatDate(workOrder.created_date) : "—"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Контрагент</span>
              <span>{workOrder.customer_name || "—"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Телефон</span>
              <span>{workOrder.phone || "—"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Организация</span>
              <span>{workOrder.organization || "—"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Плательщик</span>
              <span>{workOrder.payer_name || "—"}</span>
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
              <span className="detail-label">Вид ремонта</span>
              <span>{workOrder.repair_type || "—"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Внутренний</span>
              <span>{workOrder.is_internal ? "Да" : "Нет"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">VIN</span>
              <span>{workOrder.vin || "—"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Сумма</span>
              <span>{formatAmount(workOrder.amount)}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">% оплаты</span>
              <span>{formatPercent(workOrder.payment_percent)}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Оплачено</span>
              <span>{formatAmount(workOrder.paid_amount)}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Остаток долга</span>
              <span>{formatAmount(workOrder.debt_amount)}</span>
            </div>
          </div>

          <div className="card">
            <WorkOrderLineTabs
              labor={workOrder.labor}
              parts={workOrder.parts}
              statusHistory={workOrder.status_history}
              paymentEvents={workOrder.payment_events}
            />
          </div>
        </>
      )}
    </div>
  );
}
