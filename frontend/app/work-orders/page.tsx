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
    data = await getWorkOrders({
      limit: 5000,
      paidFrom: params.paid_from,
      paidTo: params.paid_to,
    });
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div>
      <h1>Work Orders</h1>

      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить данные: {error}</p>
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
