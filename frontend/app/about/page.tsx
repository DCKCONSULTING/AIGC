import { publicDocMetadata, PublicDoc } from "@/components/home/PublicDoc";

export const metadata = publicDocMetadata(
  "About MISA",
  "MISA is an AI video studio made in Malaysia for business owners who need social video.",
);

export default function AboutPage() {
  return (
    <PublicDoc
      title="About MISA"
      lead="MISA is an AI video studio for Malaysian businesses. You bring an idea or product photos. Mike and Sara turn it into a finished social video."
    >
      <p>
        The public homepage is for understanding the product and starting your first video. The
        authenticated AI Studio is where brands, products, scenes, voice, captions and export live.
      </p>
      <p>Made with care in Malaysia.</p>
    </PublicDoc>
  );
}
