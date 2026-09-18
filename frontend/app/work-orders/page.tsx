import { WorkOrdersTable } from "@/components/WorkOrdersTable";

// Data loads client-side now (see WorkOrdersTable and lib/work-orders-cache.ts,
// which lets it render instantly from the dashboard's prefetch instead of
// every visit paying for a fresh multi-thousand-row fetch) - this page itself
// no longer fetches anything, but stays dynamic since it still reads
// searchParams per request.
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
  // the dashboard's "Оплаты за период" tile. Applied server-side by the
  // fetch itself (see lib/work-orders-cache.ts loadWorkOrdersFiltered).
  paid_from?: string;
  paid_to?: string;
};

export default async function WorkOrdersPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;

  return (
    <div>
      <h1>Work Orders</h1>

      <WorkOrdersTable
        initialStatus={params.status}
        initialDateFrom={params.date_from}
        initialDateTo={params.date_to}
        initialClosedFrom={params.closed_from}
        initialClosedTo={params.closed_to}
        initialDepartment={params.departments}
        paidFrom={params.paid_from}
        paidTo={params.paid_to}
      />
    </div>
  );
}
