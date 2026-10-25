import { CashView } from "@/components/cash/CashView";
import { getCashContext } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

// Never statically prerendered - the page is per user (which cash desks they
// may see comes from the server, by their own id).
export const dynamic = "force-dynamic";

export default async function CashPage() {
  const user = await getCurrentUser();
  let context: Awaited<ReturnType<typeof getCashContext>> | null = null;
  let error: string | null = null;

  if (user) {
    try {
      context = await getCashContext({ id: user.id, fullName: user.fullName });
    } catch (err) {
      error = err instanceof Error ? err.message : "Unknown error";
    }
  }

  return (
    <div className="wide-page cash-page">
      {error && (
        <div className="card" style={{ borderColor: "var(--down)" }}>
          <h1 className="planner-title">Касса</h1>
          <p>Не удалось загрузить данные: {error}</p>
        </div>
      )}

      {context && context.workshops.length === 0 && (
        <div className="card">
          <h1 className="planner-title">Касса</h1>
          <p>
            У вас не выбран цех, поэтому касса недоступна. Обратитесь к администратору: ему нужно указать вам
            подразделение и цех в Настройках (или включить вашей роли «Все подразделения»).
          </p>
        </div>
      )}

      {context && context.workshops.length > 0 && <CashView context={context} />}
    </div>
  );
}
