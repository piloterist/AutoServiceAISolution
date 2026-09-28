import type { Metadata } from "next";

import { Nav } from "@/components/Nav";
import { getCurrentUser } from "@/lib/session";

import "./globals.css";

export const metadata: Metadata = {
  title: "AutoService Platform",
  description: "Multi-tenant hosted platform for auto service work order management",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Resolved here (not in Nav itself) so Nav can stay a plain client
  // component - the signed cookie is only readable server-side, and
  // middleware.ts already guarantees this is valid/non-null for every page
  // it lets through (the login page is the only exception, where user is
  // null and Nav renders nothing regardless - see Nav.tsx).
  const user = await getCurrentUser();

  // Correct for a Russian-UI product regardless (screen readers, spell
  // check, etc.) - but note this does NOT control a native
  // <input type="date">'s displayed day/month/year order, which the
  // browser picks from its own locale, not the page's `lang`; see
  // components/DateInput.tsx for how those are actually kept at
  // ДД.ММ.ГГГГ for every visitor.
  return (
    // The anti-FOUC script below sets data-theme on this element before
    // React hydrates (that's the whole point - painting the right theme on
    // first frame, not a moment later), which otherwise makes React flag a
    // hydration mismatch on every load even though nothing is actually
    // broken. suppressHydrationWarning tells React that's expected for
    // this element - see https://nextjs.org/docs/messages/react-hydration-error.
    <html lang="ru" suppressHydrationWarning>
      <body>
        {/* Applies a saved theme choice before first paint - without this,
            the page would flash light and then snap to dark a moment later
            for anyone who picked dark mode (see components/ThemeToggle).
            Falls back to the account's own default theme (set in Settings ->
            Пользователи) when the visitor hasn't picked one by hand yet - a
            manual pick in localStorage always wins once made. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("theme");var accountTheme=${JSON.stringify(user?.theme ?? null)};if(t!=="light"&&t!=="dark"){t=accountTheme;}if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t);}}catch(e){}})();`,
          }}
        />
        <div className="app-shell">
          <Nav user={user} />
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
