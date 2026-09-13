import { HealthIndicator } from "@/components/HealthIndicator";

export default function HomePage() {
  return (
    <div className="card">
      <h1>AutoService Platform</h1>
      <p>Application shell is up. This instance is configured per deployment via environment variables.</p>
      <HealthIndicator />
    </div>
  );
}
