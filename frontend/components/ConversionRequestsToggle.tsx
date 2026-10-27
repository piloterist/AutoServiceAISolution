"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

/** "Включить заявки на ремонт" under the conversion donuts (Аналитика): off by default.
 * On, a repair request created after a call counts in the conversion like a work order
 * (see backend conversion_service). The choice lives in a session cookie so it survives the
 * dashboard's own filters; the page is a Server Component, so it just re-renders. */
export function ConversionRequestsToggle({ checked }: { checked: boolean }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <label className="conversion-requests-toggle">
      <input
        type="checkbox"
        checked={checked}
        disabled={pending}
        onChange={(event) => {
          document.cookie = `conv_requests=${event.target.checked ? "1" : "0"}; path=/; SameSite=Lax`;
          startTransition(() => router.refresh());
        }}
      />
      <span>Включить заявки на ремонт</span>
      <span className="conversion-requests-hint">
        заявка после звонка считается в конверсию как заказ-наряд
      </span>
    </label>
  );
}
