import Link from "next/link";

import type { ConversionSummary } from "@/lib/backend-api";
import {
  conversionHref,
  conversionWorkOrdersHref,
  type Cohort,
  type ConversionWorkOrdersKind,
} from "@/lib/conversion-cohorts";

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
  cohort?: Cohort; // no cohort and no workOrders = a plain row, not a link
  workOrders?: ConversionWorkOrdersKind;
};

type Figures = {
  // Which "Конверсия" selection the donut itself links to (none = not a link).
  cohort?: Cohort;
  pct: number | null;
  converted: number;
  base: number;
  baseLabel: string;
  caption: string;
  rows: Row[];
};

/** The numbers behind each of the two donuts. The rules themselves (unique
 * numbers, a real conversation with a defined topic, a work order created
 * after the call and before the next conversation) live in the backend -
 * see conversion_service.get_conversion_summary. */
function figuresFor(variant: "new" | "existing" | "sources", s: ConversionSummary): Figures {
  if (variant === "sources") {
    const total = s.work_orders_total;
    const afterPct = total > 0 ? (s.work_orders_after_call / total) * 100 : null;
    const withoutPct = total > 0 ? (s.work_orders_without_call / total) * 100 : 0;
    return {
      pct: afterPct,
      converted: s.work_orders_after_call,
      base: total,
      baseLabel: "заказ-нарядов",
      caption: "после звонка",
      rows: [
        {
          label: "Всего заказ-нарядов",
          hint: "Заказ-наряды, созданные за период (без гарантийных; внутренние — если в настройках включено их исключение)",
          value: total,
          workOrders: "total",
        },
        {
          label: "После звонка",
          hint: "Заказ-наряд создан после целевого звонка клиента с этого же номера — того звонка, который учтён в конверсии",
          value: s.work_orders_after_call,
          workOrders: "after_call",
        },
        {
          label: "Без звонка",
          hint: `Все остальные: клиент приехал сам, звонил до периода, звонок был не целевой или с другого номера (${withoutPct.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}% от всех)`,
          value: s.work_orders_without_call,
          workOrders: "without_call",
        },
      ],
    };
  }

  const totalCalls: Row = {
    label: "Всего звонков",
    hint: "Все входящие и исходящие звонки периода, все клиенты (без сотрудников)",
    value: s.calls_total,
    cohort: "all",
  };
  const targetCalls: Row = {
    label: "Целевые звонки",
    hint: "Новые клиенты + существующие клиенты: уникальные номера с целевым разговором (тема определена или разговор дольше 20 секунд). Не входят звонки по уже идущему заказу («когда будет готова», «статус») и звонки сотрудников. Подробности — по значку «?» у заголовка",
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
      caption: "конверсия",
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
          hint: "Новые клиенты (уникальные номера), по которым после разговора по теме создан хотя бы один заказ-наряд или заявка на ремонт; от «Новых клиентов» это и есть процент конверсии",
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
          label: "Заявок на ремонт",
          hint: `Заявки на ремонт по новым клиентам после разговора по теме (бесплатный заезд на дефектовку), от ${formatInt(s.converted_new_clients)} номеров. Заявка засчитывается в конверсию как заказ-наряд: номер, по которому есть заявка или заказ-наряд, считается один раз`,
          value: s.repair_requests_new_clients,
          cohort: "new_converted",
          workOrders: "new_requests",
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
    caption: "конверсия",
    rows: [
      totalCalls,
      targetCalls,
      {
        label: "Существующие клиенты",
        hint: `Целевые номера клиентов, у которых к моменту звонка уже был заказ-наряд (в любом статусе, в том числе незакрытый)`,
        value: s.existing_clients,
        cohort: "existing_counted",
      },
      {
        label: "Дошли до заказ-наряда",
        hint: "Существующие клиенты (уникальные номера), по которым после разговора по теме создан хотя бы один заказ-наряд или заявка на ремонт; от «Существующих клиентов» это и есть процент конверсии",
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
        label: "Заявок на ремонт",
        hint: `Заявки на ремонт по существующим клиентам после разговора по теме (бесплатный заезд на дефектовку), от ${formatInt(s.converted_existing_clients)} номеров. Заявка засчитывается в конверсию как заказ-наряд: номер, по которому есть заявка или заказ-наряд, считается один раз`,
        value: s.repair_requests_existing_clients,
        cohort: "existing_converted",
        workOrders: "existing_requests",
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

/** The donut itself: a link into Телефония -> Конверсия, or a plain block when
 * the figure has no call list behind it (the order sources). */
function DonutWrap({ href, children }: { href: string | null; children: React.ReactNode }) {
  if (href === null) return <div className="conversion-donut-chart">{children}</div>;
  return (
    <Link
      className="conversion-donut-chart conversion-donut-link"
      href={href}
      title="Открыть звонки в Телефония → Конверсия"
    >
      {children}
    </Link>
  );
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
  includeRequests = false,
}: {
  summary: ConversionSummary | null;
  variant: "new" | "existing" | "sources";
  // "Включить заявки на ремонт": the figures already count them; show their rows and carry
  // the choice into the links so the lists match the donut.
  includeRequests?: boolean;
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
      : variant === "sources"
        ? `После звонка ${formatPct(pct)}: ${figures.converted} из ${figures.base} ${figures.baseLabel}`
        : `Конверсия ${formatPct(pct)}: ${figures.converted} из ${figures.base} ${figures.baseLabel}`;
  const stroke =
    variant === "new" ? "var(--chart-series)" : variant === "existing" ? "var(--chart-series-2)" : "#2f9e5b";

  return (
    <div className="conversion-donut">
      <DonutWrap
        href={
          figures.cohort
            ? conversionHref(summary.start_date, summary.end_date, figures.cohort, departments, includeRequests)
            : null
        }
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
              stroke={stroke}
              strokeWidth={STROKE}
              strokeLinecap="round"
              strokeDasharray={`${dash} ${CIRCUMFERENCE - dash}`}
              transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
            />
          )}
        </svg>
        <div className="conversion-donut-center">
          <span className="conversion-donut-pct">{pct === null ? "—" : formatPct(pct)}</span>
          <span className="conversion-donut-caption">{figures.caption}</span>
        </div>
      </DonutWrap>

      <dl className="conversion-donut-numbers">
        {figures.rows
          .filter((row) => includeRequests || !row.workOrders?.endsWith("_requests"))
          .map((row) =>
          row.workOrders || row.cohort ? (
            <Link
              key={row.label}
              className="conversion-donut-row"
              href={
                row.workOrders
                  ? conversionWorkOrdersHref(
                      row.workOrders,
                      summary.start_date,
                      summary.end_date,
                      departments,
                      includeRequests,
                    )
                  : conversionHref(
                      summary.start_date,
                      summary.end_date,
                      row.cohort as Cohort,
                      departments,
                      includeRequests,
                    )
              }
              title={row.hint}
            >
              <dt>{row.label}</dt>
              <dd>{formatInt(row.value)}</dd>
            </Link>
          ) : (
            <div key={row.label} className="conversion-donut-row conversion-donut-row--plain" title={row.hint}>
              <dt>{row.label}</dt>
              <dd>{formatInt(row.value)}</dd>
            </div>
          ),
        )}
      </dl>

    </div>
  );
}
