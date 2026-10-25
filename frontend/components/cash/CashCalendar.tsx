"use client";

import { useEffect, useState } from "react";

const MONTHS = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function monthOf(iso: string): { year: number; month: number } {
  return { year: Number(iso.slice(0, 4)), month: Number(iso.slice(5, 7)) - 1 };
}

/** A month calendar for picking the cash-book day (product ask, 2026-10-24):
 * today is marked with a colour, the selected day / period is highlighted,
 * and days inside the locked period get a tint. Picking a day selects just
 * that day (the С/По fields beside it follow). */
export function CashCalendar({
  from,
  to,
  today,
  lockFrom,
  lockTo,
  onSelectDay,
}: {
  from: string;
  to: string;
  today: string;
  lockFrom: string | null;
  lockTo: string | null;
  onSelectDay: (iso: string) => void;
}) {
  const [view, setView] = useState(() => monthOf(from));

  // Follow the selected day when it is changed from outside (the С field).
  useEffect(() => {
    setView(monthOf(from));
  }, [from]);

  const moveMonth = (delta: number) => {
    setView((prev) => {
      const index = prev.year * 12 + prev.month + delta;
      return { year: Math.floor(index / 12), month: ((index % 12) + 12) % 12 };
    });
  };

  const firstWeekday = (new Date(Date.UTC(view.year, view.month, 1)).getUTCDay() + 6) % 7; // Mon = 0
  const daysInMonth = new Date(Date.UTC(view.year, view.month + 1, 0)).getUTCDate();
  const cells: (string | null)[] = [
    ...Array<null>(firstWeekday).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => `${view.year}-${pad(view.month + 1)}-${pad(i + 1)}`),
  ];

  return (
    <div className="cash-calendar">
      <div className="cash-calendar-head">
        <button type="button" className="cash-calendar-nav" onClick={() => moveMonth(-1)} aria-label="Предыдущий месяц">
          ‹
        </button>
        <strong>
          {MONTHS[view.month]} {view.year}
        </strong>
        <button type="button" className="cash-calendar-nav" onClick={() => moveMonth(1)} aria-label="Следующий месяц">
          ›
        </button>
      </div>

      <div className="cash-calendar-grid">
        {WEEKDAYS.map((day) => (
          <span key={day} className="cash-calendar-weekday">
            {day}
          </span>
        ))}
        {cells.map((iso, index) => {
          if (iso === null) return <span key={`blank-${index}`} />;
          const classes = ["cash-calendar-day"];
          if (iso === today) classes.push("cash-calendar-day--today");
          if (iso >= from && iso <= to) classes.push("cash-calendar-day--selected");
          if (lockFrom && lockTo && iso >= lockFrom && iso <= lockTo) classes.push("cash-calendar-day--locked");
          return (
            <button key={iso} type="button" className={classes.join(" ")} onClick={() => onSelectDay(iso)}>
              {Number(iso.slice(8, 10))}
            </button>
          );
        })}
      </div>

      <div className="cash-calendar-foot">
        <button type="button" className="admin-btn" onClick={() => onSelectDay(today)}>
          Сегодня
        </button>
        <span className="cash-calendar-legend">
          <i className="cash-calendar-dot cash-calendar-dot--today" /> сегодня
          <i className="cash-calendar-dot cash-calendar-dot--selected" /> выбрано
        </span>
      </div>
    </div>
  );
}
