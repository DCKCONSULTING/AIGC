import { publicDocMetadata, PublicDoc } from "@/components/home/PublicDoc";

export const metadata = publicDocMetadata(
  "Terms",
  "Terms for using the MISA public homepage and AI Studio.",
);

export default function TermsPage() {
  return (
    <PublicDoc
      title="Terms"
      lead="By using MISA you agree to use the studio for lawful product and business videos, and to supply accurate product information."
    >
      <p>
        Generated videos are drafts until you review them. You remain responsible for claims, offers
        and product appearance in anything you publish.
      </p>
    </PublicDoc>
  );
}
