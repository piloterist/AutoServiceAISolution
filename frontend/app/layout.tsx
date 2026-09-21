import type { Metadata } from "next";
import { cookies } from "next/headers";

import { Nav } from "@/components/Nav";
import { readSessionToken, SESSION_COOKIE_NAME } from "@/lib/auth";

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
  const token = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  const user = await readSessionToken(token);

  return (
    <html lang="en">
      <body>
        {/* Applies a saved theme choice before first paint - without this,
            the page would flash light and then snap to dark a moment later
            for anyone who picked dark mode (see components/ThemeToggle). */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              '(function(){try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t);}}catch(e){}})();',
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
