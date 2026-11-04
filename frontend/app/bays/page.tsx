import { BaysView } from "@/components/bays/BaysView";
import { getWorkshops } from "@/lib/backend-api";
import { ROLE_ADMIN } from "@/lib/auth";
import { getCurrentUser } from "@/lib/session";

// Never statically prerendered - the page depends on the logged-in user.
export const dynamic = "force-dynamic";

export default async function BaysPage() {
  const user = await getCurrentUser();
  let workshops: Awaited<ReturnType<typeof getWorkshops>> = [];
  let error: string | null = null;

  try {
    workshops = await getWorkshops();
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div className="wide-page">
      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <h1 className="planner-title">Боксы</h1>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {!error && workshops.length === 0 && (
        <div className="card">
          <h1 className="planner-title">Боксы</h1>
          <p>Сначала создайте цеха в Настройках.</p>
        </div>
      )}

      {workshops.length > 0 && (
        <BaysView
          workshops={workshops}
          defaultWorkshopId={user?.workshopId ?? null}
          isAdmin={user?.role === ROLE_ADMIN}
        />
      )}
    </div>
  );
}
