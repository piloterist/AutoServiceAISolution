"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ThemeToggle } from "@/components/ThemeToggle";
import type { SessionUser } from "@/lib/auth";
import { NAV_TABS } from "@/lib/nav-tabs";

const ROLE_ADMIN = "Админ";

export function Nav({ user }: { user: SessionUser | null }) {
  const pathname = usePathname();

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
      ? [...visibleTabs.map((t) => ({ href: t.key, label: t.label })), { href: "/settings", label: "Settings" }]
      : visibleTabs.map((t) => ({ href: t.key, label: t.label }));

  return (
    <nav className="nav">
      <Link href="/" className="nav-brand">
        AutoService Platform
      </Link>
      <ul className="nav-list">
        {items.map((item) => (
          <li key={item.href}>
            <Link
              href={item.href}
              className={pathname === item.href ? "nav-link active" : "nav-link"}
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
