import { redirect } from "next/navigation";

export default function ReviewSettingsPage() {
  redirect("/collection/settings?tab=reviews");
}
