import type { Metadata } from "next";

import { Nav } from "@/components/Nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "AutoService Platform",
  description: "Multi-tenant hosted platform for auto service work order management",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
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
          <Nav />
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
