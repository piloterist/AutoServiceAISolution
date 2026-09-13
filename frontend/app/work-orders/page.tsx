import { getWorkOrders } from "@/lib/backend-api";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function formatAmount(amount: string): string {
  const value = Number(amount);
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value) + " ₽";
}

export default async function WorkOrdersPage() {
  let data;
  let error: string | null = null;

  try {
    data = await getWorkOrders({ limit: 500 });
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
        <>
          <p className="table-meta">
            Показано {data.items.length} из {data.total}
          </p>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Номер</th>
                  <th>Автомобиль</th>
                  <th>Заказчик</th>
                  <th>Плательщик</th>
                  <th className="num">Сумма</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDate(item.document_date)}</td>
                    <td>{item.external_number}</td>
                    <td>{item.vehicle_description ?? "—"}</td>
                    <td>{item.customer_name ?? "—"}</td>
                    <td>{item.payer_name ?? "—"}</td>
                    <td className="num">{formatAmount(item.amount)}</td>
                  </tr>
                ))}
                {data.items.length === 0 && (
                  <tr>
                    <td colSpan={6} className="table-empty">
                      Пока нет данных.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
