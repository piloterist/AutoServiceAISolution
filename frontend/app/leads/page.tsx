import { redirect } from "next/navigation";

// "Заявки" is now the "Заявки с сайта" tab of Входящие лиды (/telephony); this
// keeps old links and bookmarks working, including the planner's ?id= deep link.
export default async function LeadsPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>;
}) {
  const { id } = await searchParams;
  const query = new URLSearchParams({ tab: "leads" });
  if (id) query.set("id", id);
  redirect(`/telephony?${query.toString()}`);
}
