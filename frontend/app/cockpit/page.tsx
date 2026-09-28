import { CockpitView } from "@/components/cockpit/CockpitView";
import { getCockpitSnapshot, getWorkshopOptions } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

// Same reasoning as every other data page here - never statically
// prerendered, this always needs a fresh backend read for "this month".
export const dynamic = "force-dynamic";

export default async function CockpitPage() {
  const user = await getCurrentUser();

  let snapshot;
  let workshops: Awaited<ReturnType<typeof getWorkshopOptions>> = [];
  let error: string | null = null;

  try {
    [snapshot, workshops] = await Promise.all([getCockpitSnapshot(), getWorkshopOptions()]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  if (error || !snapshot) {
    return (
      <div className="cockpit-page">
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <p>Не удалось загрузить Cockpit: {error}</p>
        </div>
      </div>
    );
  }

  return <CockpitView initialSnapshot={snapshot} workshops={workshops} userId={user?.id ?? "anon"} />;
}
