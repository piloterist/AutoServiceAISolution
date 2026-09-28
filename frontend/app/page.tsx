import { redirect } from "next/navigation";

// Cockpit is the app's landing page - see components/cockpit/CockpitView.tsx.
// middleware.ts still gates this same as any other page, so a role without
// the /cockpit tab lands on its own first allowed tab instead, not here.
export default function HomePage() {
  redirect("/cockpit");
}
