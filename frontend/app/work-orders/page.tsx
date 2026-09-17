import { WorkOrdersTable } from "@/components/WorkOrdersTable";
import { getWorkOrders } from "@/lib/backend-api";

// This page must never be statically prerendered: if the backend happens to
// be reachable at build time (e.g. a Docker build with network access),
// Next.js can otherwise freeze it as a static page with build-time data,
// which would then never update after deploy until the next rebuild.
export const dynamic = "force-dynamic";

type SearchParams = {
  status?: string;
  date_from?: string;
  date_to?: string;
  closed_from?: string;
  closed_to?: string;
  departments?: string;
  // Distinct from date_from/date_to (document_date) - restricts to work
  // orders with a real payment (paid_at) in this range, e.g. arriving from
  // the dashboard's "Оплаты за период" tile. Has to be applied server-side
  // (unlike the other filters, which filter the already-fetched full list
  // client-side in WorkOrdersTable) since payment events aren't part of
  // the list payload.
  paid_from?: string;
  paid_to?: string;
};

export default async function WorkOrdersPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;

  let data;
  let error: string | null = null;

  try {
    // Comfortably above the real row count - this page fetches everything
    // once and filters client-side (see WorkOrdersTable), so a limit that's
    // too low silently drops older records from every filter/search, not
    // just from the visible list. 5000 did exactly that once the export
    // history grew past it. truncated (below) is a safety net in case this
    // number is ever outgrown again.
    data = await getWorkOrders({
      limit: 50_000,
      paidFrom: params.paid_from,
      paidTo: params.paid_to,
    });
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  const truncated = data ? data.total > data.items.length : false;

  return (
    <div>
      <h1>Work Orders</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {truncated && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>
            Загружено {data!.items.length.toLocaleString("ru-RU")} из{" "}
            {data!.total.toLocaleString("ru-RU")} заказ-нарядов — фильтры и поиск сейчас работают
            только по загруженной части. Сообщите разработчику, лимит нужно увеличить.
          </p>
        </div>
      )}

      {data && (
        <WorkOrdersTable
          items={data.items}
          initialStatus={params.status}
          initialDateFrom={params.date_from}
          initialDateTo={params.date_to}
          initialClosedFrom={params.closed_from}
          initialClosedTo={params.closed_to}
          initialDepartment={params.departments}
          paidFrom={params.paid_from}
          paidTo={params.paid_to}
        />
      )}
    </div>
  );
}
