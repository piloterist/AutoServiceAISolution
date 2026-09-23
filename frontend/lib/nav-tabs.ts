// The app's top-nav tabs, shared between Nav.tsx (renders the links),
// middleware.ts (Edge runtime - enforces per-role visibility from the
// session cookie, see lib/auth.ts's SessionUser.allowedTabs) and the
// Settings "Права доступа" admin table (components/settings/
// RoleTabVisibilityCard.tsx - lets an Admin edit which roles see which of
// these). Mirrors backend app/models/role_tab_visibility.py's NAV_TAB_KEYS -
// keep both lists in sync if a tab is ever added/removed/renamed.
//
// /settings is NOT one of these - it stays hardcoded to ROLE_ADMIN in
// middleware.ts, deliberately never configurable here, so a role's own
// visible-tabs list can never be edited into a state that locks every admin
// out of the page that edits it.
export const NAV_TABS = [
  { key: "/dashboard", label: "Dashboard" },
  { key: "/work-orders", label: "Work Orders" },
  { key: "/planner", label: "Planner" },
  { key: "/kanban", label: "Kanban" },
  { key: "/employees", label: "Employees" },
  { key: "/analytics", label: "Analytics" },
] as const;

export type NavTabKey = (typeof NAV_TABS)[number]["key"];

export const NAV_TAB_KEYS: NavTabKey[] = NAV_TABS.map((t) => t.key);
