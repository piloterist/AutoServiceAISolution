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
        <div className="app-shell">
          <Nav />
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
