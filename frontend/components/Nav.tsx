"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { ThemeToggle } from "@/components/ThemeToggle";
import type { SessionUser } from "@/lib/auth";
import { NAV_TABS } from "@/lib/nav-tabs";
import { monthRange } from "@/lib/period";
import { readPeriodOverride } from "@/lib/period-override";

const ROLE_ADMIN = "Админ";

export function Nav({ user }: { user: SessionUser | null }) {
  const pathname = usePathname();
  const router = useRouter();

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
              className={pathname === item.href ? "nav-link active" : "nav-link"}
              onClick={(e) => handleNavClick(e, item.href)}
            >
              {item.label}
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
