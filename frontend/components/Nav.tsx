"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ThemeToggle } from "@/components/ThemeToggle";
import type { SessionUser } from "@/lib/auth";

// Placeholder top-level navigation. Items map to future core modules; actual
// enabled modules per client instance will come from configuration/feature
// flags, not from this hardcoded list once that layer exists. "Settings" is
// separate - it's role-gated below, not just another module.
const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/work-orders", label: "Work Orders" },
  { href: "/planner", label: "Planner" },
  { href: "/kanban", label: "Kanban" },
  { href: "/employees", label: "Employees" },
  { href: "/analytics", label: "Analytics" },
];

const ROLE_ADMIN = "Админ";

export function Nav({ user }: { user: SessionUser | null }) {
  const pathname = usePathname();

  // No point showing the app chrome on the login page itself - every link
  // in it just bounces back here via middleware until you're logged in.
  if (pathname === "/login") return null;

  const items = user?.role === ROLE_ADMIN ? [...NAV_ITEMS, { href: "/settings", label: "Settings" }] : NAV_ITEMS;

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
