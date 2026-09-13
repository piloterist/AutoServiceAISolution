// Plain server-rendered GET form - no client JS needed. Submitting it just
// navigates to /dashboard?date_from=...&date_to=...&departments=a&departments=b,
// which the dashboard page (a Server Component) reads via searchParams and
// uses to re-fetch already-filtered data from the backend. "All departments"
// is simply "none of the checkboxes checked" - no special case needed since
// that's exactly what the backend's own optional `departments` filter means.
export function DashboardFilters({
  departments,
  selectedDepartments,
  dateFrom,
  dateTo,
}: {
  departments: string[];
  selectedDepartments: string[];
  dateFrom?: string;
  dateTo?: string;
}) {
  const hasActiveFilters = selectedDepartments.length > 0 || Boolean(dateFrom) || Boolean(dateTo);

  return (
    <form className="filters-form card" method="get">
      <div className="filters-row">
        <label className="filters-field">
          <span className="filters-label">С даты</span>
          <input type="date" name="date_from" defaultValue={dateFrom ?? ""} />
        </label>
        <label className="filters-field">
          <span className="filters-label">По дату</span>
          <input type="date" name="date_to" defaultValue={dateTo ?? ""} />
        </label>
      </div>

      {departments.length > 0 && (
        <div className="filters-departments">
          <span className="filters-label">Подразделение (не выбрано ни одного = все)</span>
          <div className="filters-checkboxes">
            {departments.map((dept) => (
              <label key={dept} className="filters-checkbox">
                <input
                  type="checkbox"
                  name="departments"
                  value={dept}
                  defaultChecked={selectedDepartments.includes(dept)}
                />
                {dept}
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="filters-actions">
        <button type="submit" className="filters-submit">
          Применить
        </button>
        {hasActiveFilters && (
          <a href="/dashboard" className="filters-reset">
            Сбросить фильтры
          </a>
        )}
      </div>
    </form>
  );
}
