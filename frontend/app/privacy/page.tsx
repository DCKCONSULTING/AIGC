import { publicDocMetadata, PublicDoc } from "@/components/home/PublicDoc";

export const metadata = publicDocMetadata(
  "Privacy",
  "How MISA handles prompts, product photos and account details.",
);

export default function PrivacyPage() {
  return (
    <PublicDoc
      title="Privacy"
      lead="Prompts and product photos you enter on the homepage are stored on this device until you generate a video, then carried into your brand account in AI Studio."
    >
      <p>
        Account details are used to operate your studio workspace. We do not use the public homepage
        to expose brands, products, agents or production controls.
      </p>
    </PublicDoc>
  );
}
