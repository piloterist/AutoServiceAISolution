import { DashboardFilters } from "@/components/DashboardFilters";
import { MonthlyBarChart } from "@/components/MonthlyRevenueChart";
import { RankedList, type RankedItem } from "@/components/RankedList";
import { RevenueTrendChart } from "@/components/RevenueTrendChart";
import { StatTile } from "@/components/StatTile";
import {
  type DepartmentSummaryItem,
  getDepartments,
  getDepartmentSummary,
  getMonthlySummary,
  getStatusSummary,
  getTrendSummary,
} from "@/lib/backend-api";
import { currentMonthRange, previousPeriod } from "@/lib/period";

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

function pluralWorkOrders(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return "заказ-наряд";
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return "заказ-наряда";
  return "заказ-нарядов";
}

/** The department whose revenue moved the most (up or down) between the two
 * periods - drives the insight banner's "основной вклад: ..." line. Missing
 * from one side just counts as 0 there (a department with no closed work
 * orders last period is a 100%-swing contributor this period, which is a
 * fair thing to call out). */
function topDepartmentContributor(
  current: DepartmentSummaryItem[],
  previous: DepartmentSummaryItem[],
): { department: string; deltaAmount: number } | null {
  if (current.length === 0) return null;
  const previousByDept = new Map(previous.map((d) => [d.department, Number(d.total_amount)]));

  let best: { department: string; deltaAmount: number } | null = null;
  for (const d of current) {
    const deltaAmount = Number(d.total_amount) - (previousByDept.get(d.department) ?? 0);
    if (best === null || Math.abs(deltaAmount) > Math.abs(best.deltaAmount)) {
      best = { department: d.department, deltaAmount };
    }
  }
  return best;
}

function buildInsightText({
  revenueDeltaPct,
  countDeltaPct,
  currentDepartments,
  previousDepartments,
}: {
  revenueDeltaPct: number | null;
  countDeltaPct: number | null;
  currentDepartments: DepartmentSummaryItem[];
  previousDepartments: DepartmentSummaryItem[];
}): string | null {
  // No previous-period baseline (e.g. nothing was closed in it) - a
  // percentage comparison would be meaningless, so say nothing rather than
  // show a misleading "+∞%".
  if (revenueDeltaPct === null) return null;

  const direction = revenueDeltaPct >= 0 ? "выросла" : "снизилась";
  const top = topDepartmentContributor(currentDepartments, previousDepartments);
  const contributorPhrase =
    top && Math.abs(top.deltaAmount) > 0 ? ` — основной вклад: ${top.department}` : "";
  const countPhrase =
    countDeltaPct !== null
      ? `, закрыто заказ-нарядов ${countDeltaPct >= 0 ? "больше" : "меньше"} на ${Math.abs(
          countDeltaPct,
        ).toFixed(0)}%`
      : "";

  return `Выручка ${direction} на ${Math.abs(revenueDeltaPct).toFixed(
    0,
  )}% к предыдущему периоду${contributorPhrase}${countPhrase}.`;
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const rawDateFrom = params.date_from || undefined;
  const rawDateTo = params.date_to || undefined;
  const selectedDepartments = toArray(params.departments);
  const hasActiveFilters =
    selectedDepartments.length > 0 || Boolean(rawDateFrom) || Boolean(rawDateTo);

  // Defaults to the current calendar month when the operator hasn't picked
  // a period - this is meant to be a "how's the shop doing right now"
  // screen, not one that opens onto an all-time (or empty) view.
  const { dateFrom, dateTo } =
    rawDateFrom && rawDateTo ? { dateFrom: rawDateFrom, dateTo: rawDateTo } : currentMonthRange();
  const previousRange = previousPeriod(dateFrom, dateTo);

  const filterParams = { dateFrom, dateTo, departments: selectedDepartments };
  const previousFilterParams = {
    dateFrom: previousRange.dateFrom,
    dateTo: previousRange.dateTo,
    departments: selectedDepartments,
  };

  let monthlySummary;
  let departmentSummary;
  let departmentSummaryPrevious;
  let statusSummary;
  let trendCurrent;
  let trendPrevious;
  let allDepartments: string[] = [];
  let error: string | null = null;

  try {
    const [monthlyRes, deptRes, deptPrevRes, statusRes, trendRes, trendPrevRes, departmentsRes] =
      await Promise.all([
        getMonthlySummary(filterParams),
        getDepartmentSummary(filterParams),
        getDepartmentSummary(previousFilterParams),
        getStatusSummary(filterParams),
        getTrendSummary(filterParams),
        getTrendSummary(previousFilterParams),
        getDepartments(),
      ]);
    monthlySummary = monthlyRes;
    departmentSummary = deptRes;
    departmentSummaryPrevious = deptPrevRes;
    statusSummary = statusRes;
    trendCurrent = trendRes;
    trendPrevious = trendPrevRes;
    allDepartments = departmentsRes.departments;
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  const trendCurrentItems = trendCurrent?.items ?? [];
  const trendPreviousItems = trendPrevious?.items ?? [];
  const granularity = trendCurrent?.granularity ?? "month";

  const totalAmount = trendCurrentItems.reduce((sum, item) => sum + Number(item.total_amount), 0);
  const totalCount = trendCurrentItems.reduce((sum, item) => sum + item.work_order_count, 0);
  const avgAmount = totalCount > 0 ? totalAmount / totalCount : 0;

  const prevTotalAmount = trendPreviousItems.reduce((sum, item) => sum + Number(item.total_amount), 0);
  const prevTotalCount = trendPreviousItems.reduce((sum, item) => sum + item.work_order_count, 0);
  const prevAvgAmount = prevTotalCount > 0 ? prevTotalAmount / prevTotalCount : 0;

  const revenueDeltaPct =
    prevTotalAmount > 0 ? ((totalAmount - prevTotalAmount) / prevTotalAmount) * 100 : null;
  const countDeltaPct =
    prevTotalCount > 0 ? ((totalCount - prevTotalCount) / prevTotalCount) * 100 : null;
  const avgDeltaPct = prevAvgAmount > 0 ? ((avgAmount - prevAvgAmount) / prevAvgAmount) * 100 : null;

  const revenueSpark = trendCurrentItems.map((item) => Number(item.total_amount));
  const countSpark = trendCurrentItems.map((item) => item.work_order_count);
  const avgSpark = trendCurrentItems.map((item) =>
    item.work_order_count > 0 ? Number(item.total_amount) / item.work_order_count : 0,
  );

  const departmentRanked: RankedItem[] = (departmentSummary?.items ?? []).map((item) => ({
    label: item.department,
    value: Number(item.total_amount),
    meta: `${item.work_order_count.toLocaleString("ru-RU")} ${pluralWorkOrders(item.work_order_count)}`,
  }));

  const statusItems = statusSummary?.items ?? [];
  const totalStatusCount = statusItems.reduce((sum, item) => sum + item.work_order_count, 0);
  const statusRanked: RankedItem[] = statusItems.map((item) => ({
    label: item.status,
    value: item.work_order_count,
    meta:
      totalStatusCount > 0
        ? `${((item.work_order_count / totalStatusCount) * 100).toFixed(0)}% от всех`
        : "",
  }));

  const insightText = buildInsightText({
    revenueDeltaPct,
    countDeltaPct,
    currentDepartments: departmentSummary?.items ?? [],
    previousDepartments: departmentSummaryPrevious?.items ?? [],
  });

  return (
    <div className="wide-page">
      <h1>Dashboard</h1>

      <DashboardFilters
        departments={allDepartments}
        selectedDepartments={selectedDepartments}
        dateFrom={dateFrom}
        dateTo={dateTo}
        hasActiveFilters={hasActiveFilters}
      />

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {!error && (
        <>
          {insightText && (
            <div className="insight-banner">
              <span className="insight-icon">{revenueDeltaPct !== null && revenueDeltaPct >= 0 ? "▲" : "▼"}</span>
              <p>{insightText}</p>
            </div>
          )}

          <div className="stat-row">
            <StatTile
              label="Выручка за период"
              value={`${totalAmount.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽`}
              deltaPct={revenueDeltaPct}
              sparkline={revenueSpark}
            />
            <StatTile
              label="Заказ-нарядов"
              value={totalCount.toLocaleString("ru-RU")}
              deltaPct={countDeltaPct}
              sparkline={countSpark}
            />
            <StatTile
              label="Средний чек"
              value={`${avgAmount.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽`}
              deltaPct={avgDeltaPct}
              sparkline={avgSpark}
            />
          </div>

          <p className="dashboard-note">
            Выручка везде на этой странице считается по дате закрытия заказ-наряда (кроме списка по
            статусам — там по дате создания, иначе не закрытые заказ-наряды вообще нигде бы не
            отображались).
          </p>

          <div className="dashboard-grid">
            <div className="dashboard-main">
              <div className="card">
                <h2 className="chart-title">Динамика выручки</h2>
                <p className="chart-subtitle">по дате закрытия заказ-наряда</p>
                <RevenueTrendChart
                  current={trendCurrentItems}
                  previous={trendPreviousItems}
                  granularity={granularity}
                />
              </div>

              <div className="card">
                <h2 className="chart-title">Количество заказ-нарядов по месяцам</h2>
                <p className="chart-subtitle">по дате закрытия заказ-наряда</p>
                <MonthlyBarChart data={monthlySummary?.items ?? []} metric="count" colorSlot="series-2" />
              </div>
            </div>

            <div className="dashboard-sidebar">
              <div className="card">
                <h2 className="chart-title">Выручка по подразделениям</h2>
                <p className="chart-subtitle">по дате закрытия заказ-наряда</p>
                <RankedList data={departmentRanked} kind="amount" />
              </div>

              <div className="card">
                <h2 className="chart-title">Заказ-наряды по статусам</h2>
                <p className="chart-subtitle">
                  по дате создания заказ-наряда — включает все статусы, не только закрытые
                </p>
                <RankedList
                  data={statusRanked}
                  kind="count"
                  clickable
                  dateFrom={dateFrom}
                  dateTo={dateTo}
                />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
