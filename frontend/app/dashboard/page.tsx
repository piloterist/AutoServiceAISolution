import { DashboardFilters } from "@/components/DashboardFilters";
import { DepartmentDonutChart } from "@/components/DepartmentDonutChart";
import { MonthlyBarChart } from "@/components/MonthlyRevenueChart";
import { getDepartmentSummary, getDepartments, getMonthlySummary } from "@/lib/backend-api";

// See app/work-orders/page.tsx for why this is required.
export const dynamic = "force-dynamic";

type SearchParams = {
  date_from?: string;
  date_to?: string;
  departments?: string | string[];
};

function toArray(value: string | string[] | undefined): string[] {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const dateFrom = params.date_from || undefined;
  const dateTo = params.date_to || undefined;
  const selectedDepartments = toArray(params.departments);

  const filterParams = { dateFrom, dateTo, departments: selectedDepartments };

  let summary;
  let departmentSummary;
  let allDepartments: string[] = [];
  let error: string | null = null;

  try {
    const [summaryRes, departmentSummaryRes, departmentsRes] = await Promise.all([
      getMonthlySummary(filterParams),
      getDepartmentSummary(filterParams),
      getDepartments(),
    ]);
    summary = summaryRes;
    departmentSummary = departmentSummaryRes;
    allDepartments = departmentsRes.departments;
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  const items = summary?.items ?? [];
  const totalAmount = items.reduce((sum, item) => sum + Number(item.total_amount), 0);
  const totalCount = items.reduce((sum, item) => sum + item.work_order_count, 0);
  const avgAmount = totalCount > 0 ? totalAmount / totalCount : 0;

  const donutData = (departmentSummary?.items ?? []).map((item) => ({
    label: item.department,
    value: Number(item.total_amount),
  }));

  return (
    <div>
      <h1>Dashboard</h1>

      <DashboardFilters
        departments={allDepartments}
        selectedDepartments={selectedDepartments}
        dateFrom={dateFrom}
        dateTo={dateTo}
      />

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
            <MonthlyBarChart data={items} metric="amount" colorSlot="series" />
          </div>

          <div className="card">
            <h2 className="chart-title">Количество заказ-нарядов по месяцам</h2>
            <MonthlyBarChart data={items} metric="count" colorSlot="series-2" />
          </div>

          <div className="card">
            <h2 className="chart-title">Выручка по подразделениям за период</h2>
            <DepartmentDonutChart data={donutData} />
          </div>
        </>
      )}
    </div>
  );
}
