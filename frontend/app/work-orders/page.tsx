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
  // Arriving from Cockpit's ДЗ bar (see components/cockpit/
  // InstrumentCluster.tsx) - same server-side-filter treatment as
  // paid_from/paid_to above.
  only_receivables?: string;
  workshop_id?: string;
  // Arriving from Cockpit's new "₽" lamp (see components/cockpit/
  // InstrumentCluster.tsx's openUnpaidIndividual) - seeds the "Физ.лицо"
  // checkbox and the "Оплата" bucket dropdown to its two non-full-payment
  // buckets, respectively. Client-side filters, unlike paid_from/paid_to/
  // only_receivables above - status/closed_from/closed_to (already
  // supported) carry the rest of that same deep link.
  individual?: string;
  unpaid?: string;
  // Arriving from Телефония -> "Конверсия"'s "Открыть ЗН" - restricts the
  // (client-side) list to work orders on this phone number.
  phone?: string;
  // Arriving from a conversion donut's "Заказ-нарядов" (Аналитика) - only the
  // work orders counted in that figure: new/existing clients, the dashboard's
  // period and department filter (resolved by the backend).
  conv?: string;
  conv_from?: string;
  conv_to?: string;
  conv_departments?: string;
};

export default async function WorkOrdersPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;

  return (
    <div>
      {/* No page title here on purpose (product ask, 2026-10-06) - the nav
          tab already says "Заказ Наряды", and the extra heading block just
          ate vertical space this table badly needs (virtualized, often
          hundreds of rows). */}
      <WorkOrdersTable
        initialStatus={params.status}
        initialDateFrom={params.date_from}
        initialDateTo={params.date_to}
        initialClosedFrom={params.closed_from}
        initialClosedTo={params.closed_to}
        initialDepartment={params.departments}
        paidFrom={params.paid_from}
        paidTo={params.paid_to}
        onlyReceivables={params.only_receivables === "1"}
        workshopId={params.workshop_id}
        initialOnlyIndividualCustomer={params.individual === "1"}
        initialUnpaid={params.unpaid === "1"}
        initialPhone={params.phone}
        conversionFilter={
          (params.conv === "new" || params.conv === "existing") && params.conv_from && params.conv_to
            ? {
                kind: params.conv,
                from: params.conv_from,
                to: params.conv_to,
                departments: params.conv_departments ?? "",
              }
            : undefined
        }
      />
    </div>
  );
}
