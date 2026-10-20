import { publicDocMetadata, PublicDoc } from "@/components/home/PublicDoc";

export const metadata = publicDocMetadata(
  "Contact",
  "Contact MISA about the AI video studio.",
);

export default function ContactPage() {
  return (
    <PublicDoc
      title="Contact"
      lead="Questions about creating your first video, an existing brand account, or a partnership."
    >
      <p>
        For product help, start with the{" "}
        <a href="/help" className="text-link">
          help centre
        </a>
        . For account access, use brand log in on this site.
      </p>
      <p>Email: hello@misa.my</p>
    </PublicDoc>
  );
}
