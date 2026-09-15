import Image from "next/image";

import { safeNextPath } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const params = await searchParams;
  const next = safeNextPath(params.next);

  return (
    <div className="login-page">
      <form className="login-card" method="post" action="/api/auth/login">
        <Image
          src="/pan-motors-logo.png"
          alt="Pan Motors"
          width={746}
          height={323}
          className="login-logo"
          priority
        />

        {params.error && <p className="login-error">Неверный логин или пароль</p>}

        <input type="hidden" name="next" value={next} />

        <label className="login-field">
          <span>Логин</span>
          {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the one thing on this page worth focusing */}
          <input type="text" name="username" autoComplete="username" required autoFocus />
        </label>

        <label className="login-field">
          <span>Пароль</span>
          <input type="password" name="password" autoComplete="current-password" required />
        </label>

        <button type="submit" className="login-submit">
          Войти
        </button>
      </form>
    </div>
  );
}
