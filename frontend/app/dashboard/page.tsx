import { MonthlyRevenueChart } from "@/components/MonthlyRevenueChart";
import { getMonthlySummary } from "@/lib/backend-api";

export default async function DashboardPage() {
  let summary;
  let error: string | null = null;

  try {
    summary = await getMonthlySummary();
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  const items = summary?.items ?? [];
  const totalAmount = items.reduce((sum, item) => sum + Number(item.total_amount), 0);
  const totalCount = items.reduce((sum, item) => sum + item.work_order_count, 0);
  const avgAmount = totalCount > 0 ? totalAmount / totalCount : 0;

  return (
    <div>
      <h1>Dashboard</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {summary && (
        <>
          <div className="stat-row">
            <div className="stat-tile">
              <span className="stat-label">Выручка за период</span>
              <span className="stat-value">
                {totalAmount.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽
              </span>
            </div>
            <div className="stat-tile">
              <span className="stat-label">Заказ-нарядов</span>
              <span className="stat-value">{totalCount.toLocaleString("ru-RU")}</span>
            </div>
            <div className="stat-tile">
              <span className="stat-label">Средний чек</span>
              <span className="stat-value">
                {avgAmount.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽
              </span>
            </div>
          </div>

          <div className="card">
            <h2 className="chart-title">Выручка по месяцам</h2>
            <MonthlyRevenueChart data={items} />
          </div>
        </>
      )}
    </div>
  );
}
