import { publicDocMetadata, PublicDoc } from "@/components/home/PublicDoc";

export const metadata = publicDocMetadata(
  "Help centre",
  "How to start a MISA video from an idea or product photos.",
);

export default function HelpPage() {
  return (
    <PublicDoc
      title="Help centre"
      lead="A first video starts on the homepage. Generation happens in AI Studio after you create an account."
    >
      <p>
        1. Describe what you want, or add product photos. 2. Choose 9:16 and a duration. 3. Click
        Generate my video. 4. Create a brand account if you are not signed in. 5. Finish the video
        in AI Studio.
      </p>
      <p>Your prompt and photos are kept when you are asked to log in.</p>
    </PublicDoc>
  );
}
