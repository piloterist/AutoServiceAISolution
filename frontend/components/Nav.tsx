"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import type { SessionUser } from "@/lib/auth";
import { ERRORS_CHANGED_EVENT } from "@/lib/errors-badge";
import { NAV_TABS } from "@/lib/nav-tabs";
import { monthRange } from "@/lib/period";
import { readPeriodOverride } from "@/lib/period-override";

const ROLE_ADMIN = "Админ";
const ERRORS_TAB = "/errors";
const ERRORS_POLL_MS = 60_000;

export function Nav({ user }: { user: SessionUser | null }) {
  const pathname = usePathname();
  const router = useRouter();
  const showsErrors = Boolean(user?.allowedTabs?.includes(ERRORS_TAB));
  // Сколько ошибок видеоконтроля не исправлено: вкладка «Ошибки» красная при >0, иначе серая.
  const [openErrors, setOpenErrors] = useState(0);
  const refreshErrors = useCallback(async () => {
    try {
      const res = await fetch("/api/errors/summary", { cache: "no-store" });
      if (res.ok) setOpenErrors(((await res.json()) as { open_count: number }).open_count);
    } catch {
      /* сеть моргнула - оставляем прежнее значение */
    }
  }, []);
  useEffect(() => {
    if (!showsErrors) return;
    refreshErrors();
    const timer = setInterval(refreshErrors, ERRORS_POLL_MS);
    window.addEventListener(ERRORS_CHANGED_EVENT, refreshErrors);
    return () => {
      clearInterval(timer);
      window.removeEventListener(ERRORS_CHANGED_EVENT, refreshErrors);
    };
  }, [showsErrors, refreshErrors, pathname]);

  // No point showing the app chrome on the login page itself - every link
  // in it just bounces back here via middleware until you're logged in.
  if (pathname === "/login") return null;

  // Which tabs a role can see comes from the session cookie's allowedTabs
  // (see lib/auth.ts, Settings → Пользователи → "Права доступа") - this
  // alone is only cosmetic, middleware.ts enforces the same restriction at
  // the page/API level. "Settings" is separate - not one of the
  // configurable NAV_TABS, still hardcoded to ROLE_ADMIN (see
  // middleware.ts's module comment for why).
  const visibleTabs = NAV_TABS.filter((tab) => user?.allowedTabs?.includes(tab.key));
  const items =
    user?.role === ROLE_ADMIN
      ? [...visibleTabs.map((t) => ({ href: t.key, label: t.label })), { href: "/settings", label: "Настройки" }]
      : visibleTabs.map((t) => ({ href: t.key, label: t.label }));

  // "Аналитика" picks up whatever month is currently selected on ESP (see
  // lib/period-override.ts) - read fresh at the moment of the actual click,
  // not once when Nav itself rendered (Nav lives in the root layout and
  // doesn't re-render just because CockpitView writes a new override while
  // the operator is still on /cockpit, so a value baked in earlier would go
  // stale the instant they pick a different month). Per product ask,
  // 2026-10-01: "выбранный месяц автоматически встает в фильтре на листе
  // Аналитика". Falls through to a plain navigation (DashboardPeriodSync's
  // own mount-effect fallback handles that case) when there's no override.
  const handleNavClick = (e: React.MouseEvent, href: string) => {
    if (href !== "/dashboard" || !user) return;
    const override = readPeriodOverride(user.id);
    if (!override) return;
    e.preventDefault();
    const { dateFrom, dateTo } = monthRange(override.year, override.month);
    router.push(`/dashboard?date_from=${dateFrom}&date_to=${dateTo}`);
  };

  return (
    <nav className="nav">
      <Link href="/" className="nav-brand">
        Enterprise Stability Platform
      </Link>
      <ul className="nav-list">
        {items.map((item) => (
          <li key={item.href}>
            <Link
              href={item.href}
              className={[
                pathname === item.href ? "nav-link active" : "nav-link",
                item.href === ERRORS_TAB ? (openErrors > 0 ? "nav-link--errors-open" : "nav-link--errors-clear") : "",
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={(e) => handleNavClick(e, item.href)}
            >
              {item.label}
              {item.href === ERRORS_TAB && openErrors > 0 ? ` (${openErrors})` : ""}
            </Link>
          </li>
        ))}
      </ul>
      {user && <span className="nav-user">{user.fullName}</span>}
      <a href="/api/auth/logout" className="nav-link">
        Выйти
      </a>
      <ThemeToggle />
    </nav>
  );
}
