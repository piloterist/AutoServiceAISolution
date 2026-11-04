import { ErrorsView } from "@/components/errors/ErrorsView";
import { getBayIssues } from "@/lib/backend-api";

// Never statically prerendered - the list changes every time a car enters a bay.
export const dynamic = "force-dynamic";

export default async function ErrorsPage() {
  try {
    const { issues } = await getBayIssues("all");
    return (
      <div className="wide-page">
        <ErrorsView initialIssues={issues} />
      </div>
    );
  } catch (err) {
    return (
      <div className="wide-page">
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <h1 className="planner-title">Ошибки</h1>
          <p>Не удалось загрузить данные: {err instanceof Error ? err.message : "Unknown error"}</p>
        </div>
      </div>
    );
  }
}
