import { BayHistoryView } from "@/components/bays/BayHistoryView";

// Never statically prerendered - the page depends on the logged-in user.
export const dynamic = "force-dynamic";

export default async function BayHistoryPage({
  searchParams,
}: {
  searchParams: Promise<{ bay?: string; name?: string }>;
}) {
  const { bay, name } = await searchParams;
  return (
    <div className="wide-page">
      <BayHistoryView bayId={bay ?? null} bayName={name ?? null} />
    </div>
  );
}
