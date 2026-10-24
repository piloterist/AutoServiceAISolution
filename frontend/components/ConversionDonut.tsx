import Link from "next/link";

import type { ConversionSummary } from "@/lib/backend-api";
import { conversionHref, conversionWorkOrdersHref, type Cohort } from "@/lib/conversion-cohorts";

const SIZE = 184;
const STROKE = 20;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function formatInt(value: number): string {
  return value.toLocaleString("ru-RU");
}

function formatPct(value: number): string {
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
}

// `hint` is the hover tooltip explaining how the figure is counted.
// A row links to the "Конверсия" tab (`cohort`) - or, for the work-order count,
// to the work-order list (`workOrders`).
type Row = {
  label: string;
  hint: string;
  value: number;
  cohort: Cohort;
  workOrders?: "new" | "existing";
};

type Figures = {
  // Which "Конверсия" selection the donut itself links to.
  cohort: Cohort;
  pct: number | null;
  converted: number;
  base: number;
  baseLabel: string;
  rows: Row[];
};

/** The numbers behind each of the two donuts. The rules themselves (unique
 * numbers, a real conversation with a defined topic, a work order created
 * after the call and before the next conversation) live in the backend -
 * see conversion_service.get_conversion_summary. */
function figuresFor(variant: "new" | "existing", s: ConversionSummary): Figures {
  const totalCalls: Row = {
    label: "Всего звонков",
    hint: "Все входящие и исходящие звонки периода, все клиенты (без сотрудников)",
    value: s.calls_total,
    cohort: "all",
  };
  const targetCalls: Row = {
    label: "Целевые звонки",
    hint: "Новые клиенты + существующие клиенты: уникальные номера с разговором по теме; не входят звонки, когда на момент звонка у клиента был заказ-наряд не в статусах «Закрыт»/«Отказ» или «Закрыт» в тот же день (гарантийные заказ-наряды не учитываются)",
    value: s.target_phones,
    cohort: "target",
  };

  if (variant === "new") {
    return {
      cohort: "new",
      pct: s.conversion_pct,
      converted: s.converted_new_clients,
      base: s.new_clients,
      baseLabel: "новых клиентов",
      rows: [
        totalCalls,
        targetCalls,
        {
          label: "Новые клиенты",
          hint: "Целевые номера (разговор по теме), на которые до первого звонка не было заказ-нарядов",
          value: s.new_clients,
          cohort: "new",
        },
        {
          label: "Дошли до заказ-наряда",
          hint: "Новые клиенты (уникальные номера), по которым после разговора по теме создан хотя бы один заказ-наряд; от «Новых клиентов» это и есть процент конверсии",
          value: s.converted_new_clients,
          cohort: "new_converted",
        },
        {
          label: "Заказ-нарядов",
          hint: `Заказ-наряды по новым клиентам после разговора по теме, от ${formatInt(s.converted_new_clients)} номеров`,
          value: s.work_orders_new_clients,
          cohort: "new_converted",
          workOrders: "new",
        },
        {
          label: "Остались без ответа",
          hint: "Новые номера с пропущенным звонком, которым за период никто не перезвонил (разговора так и не было)",
          value: s.unanswered_new,
          cohort: "new_unanswered",
        },
      ],
    };
  }
  return {
    cohort: "existing_counted",
    pct: s.existing_conversion_pct,
    converted: s.converted_existing_clients,
    base: s.existing_clients,
    baseLabel: "существующих клиентов",
    rows: [
      totalCalls,
      targetCalls,
      {
        label: "Существующие клиенты",
        hint: `Целевые номера (разговор по теме) клиентов, у которых к моменту звонка все прежние заказ-наряды закрыты или отказаны (исключено номеров: ${formatInt(s.existing_excluded)})`,
        value: s.existing_clients,
        cohort: "existing_counted",
      },
      {
        label: "Дошли до заказ-наряда",
        hint: "Существующие клиенты (уникальные номера), по которым после разговора по теме создан хотя бы один заказ-наряд; от «Существующих клиентов» это и есть процент конверсии",
        value: s.converted_existing_clients,
        cohort: "existing_converted",
      },
      {
        label: "Заказ-нарядов",
        hint: `Заказ-наряды по существующим клиентам после разговора по теме, от ${formatInt(s.converted_existing_clients)} номеров`,
        value: s.work_orders_existing_clients,
        cohort: "existing_converted",
        workOrders: "existing",
      },
      {
        label: "Остались без ответа",
        hint: "Существующие номера с пропущенным звонком, которым за период никто не перезвонил (разговора так и не было)",
        value: s.unanswered_existing,
        cohort: "existing_unanswered",
      },
    ],
  };
}

/** Телефония -> конверсия в заказ-наряды за период (product ask,
 * 2026-10-24): a donut whose centre is the conversion % and, beside it, the
 * numbers it is built from. "new" = clients with no earlier work order,
 * "existing" = repeat clients (see figuresFor). Pure presentation, no client
 * state. */
export function ConversionDonut({
  summary,
  variant,
  departments = [],
}: {
  summary: ConversionSummary | null;
  variant: "new" | "existing";
  // The dashboard's department filter, carried into the links so the tab
  // shows the same workshop.
  departments?: string[];
}) {
  if (!summary) {
    return <p className="chart-empty">Нет данных по телефонии за выбранный период.</p>;
  }

  const figures = figuresFor(variant, summary);
  const { pct } = figures;
  const filled = pct === null ? 0 : Math.min(Math.max(pct, 0), 100);
  const dash = (filled / 100) * CIRCUMFERENCE;
  const label =
    pct === null
      ? `Нет ${figures.baseLabel} за период`
      : `Конверсия ${formatPct(pct)}: ${figures.converted} из ${figures.base} ${figures.baseLabel}`;

  return (
    <div className="conversion-donut">
      <Link
        className="conversion-donut-chart conversion-donut-link"
        href={conversionHref(summary.start_date, summary.end_date, figures.cohort, departments)}
        title="Открыть звонки в Телефония → Конверсия"
      >
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={label}>
          <title>{label}</title>
          {/* Recessive track = the clients that did not convert. */}
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="var(--chart-gridline)"
            strokeWidth={STROKE}
          />
          {dash > 0 && (
            <circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke={variant === "new" ? "var(--chart-series)" : "var(--chart-series-2)"}
              strokeWidth={STROKE}
              strokeLinecap="round"
              strokeDasharray={`${dash} ${CIRCUMFERENCE - dash}`}
              transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
            />
          )}
        </svg>
        <div className="conversion-donut-center">
          <span className="conversion-donut-pct">{pct === null ? "—" : formatPct(pct)}</span>
          <span className="conversion-donut-caption">конверсия</span>
        </div>
      </Link>

      <dl className="conversion-donut-numbers">
        {figures.rows.map((row) => (
          <Link
            key={row.label}
            className="conversion-donut-row"
            href={
              row.workOrders
                ? conversionWorkOrdersHref(row.workOrders, summary.start_date, summary.end_date, departments)
                : conversionHref(summary.start_date, summary.end_date, row.cohort, departments)
            }
            title={row.hint}
          >
            <dt>{row.label}</dt>
            <dd>{formatInt(row.value)}</dd>
          </Link>
        ))}
      </dl>

    </div>
  );
}
