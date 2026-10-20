export const HOME_DRAFT_KEY = "misa.home.draft";

export const HOME_FORMATS = [
  { id: "9:16", label: "9:16", hint: "TikTok, Reels, Shorts" },
  { id: "1:1", label: "1:1", hint: "Feed posts" },
  { id: "16:9", label: "16:9", hint: "YouTube, landscape" },
] as const;

export const HOME_DURATIONS = [15, 30, 45] as const;

export type HomeAspect = (typeof HOME_FORMATS)[number]["id"];
export type HomeDuration = (typeof HOME_DURATIONS)[number];

export type HomePhoto = {
  name: string;
  type: string;
  dataUrl: string;
};

export type HomeDraft = {
  prompt: string;
  aspect: HomeAspect;
  duration: HomeDuration;
  photos: HomePhoto[];
  intent?: string;
  savedAt: number;
};

export const EXAMPLE_PROMPTS = [
  {
    id: "raya",
    chip: "Try: “Promote my Raya collection”",
    prompt:
      "Promote my Raya collection. Warm festive lighting, family gathering mood, Bahasa Melayu voice, 15-second hook for TikTok.",
  },
  {
    id: "photo-ad",
    chip: "“Turn this product photo into an ad”",
    prompt:
      "Turn this product photo into an ad. Keep the product looking exactly as supplied. Clear hook, then a simple call to action.",
  },
  {
    id: "bm-explainer",
    chip: "“Create a Bahasa Melayu explainer”",
    prompt:
      "Create a Bahasa Melayu explainer for my product. Calm, clear, and easy to follow. Captions for TikTok and Reels.",
  },
] as const;

export const STARTING_POINTS = [
  {
    id: "launch",
    title: "Launch a product",
    text: "Turn product photos into a short launch video with a clear hook and call to action.",
    prompt:
      "Create a 15-second launch video for my product. Open with a strong hook, show the product clearly, and end with a call to action. English or Bahasa Melayu is fine.",
  },
  {
    id: "campaign",
    title: "Promote a seasonal campaign",
    text: "Create content for Raya, Merdeka, Chinese New Year, Deepavali and year-end sales.",
    prompt:
      "Promote my seasonal campaign. Festive but not touristy. Suitable for Raya, Merdeka, Chinese New Year, Deepavali or year-end sales. Short, shareable, Bahasa Melayu captions.",
  },
  {
    id: "explain",
    title: "Explain your service",
    text: "Transform a business idea into an easy-to-follow visual explainer.",
    prompt:
      "Create a Bahasa Melayu explainer for my service. Simple scenes, clear voice, captions for people watching without sound.",
  },
  {
    id: "social",
    title: "Keep social media active",
    text: "Create multiple short videos from one campaign, formatted for TikTok, Reels and Shorts.",
    prompt:
      "Create a short social video from this campaign, formatted for TikTok, Reels and Shorts. Keep it 15 seconds with a hook in the first two seconds.",
  },
] as const;

export const EXAMPLE_VIDEOS = [
  {
    id: "ad",
    src: "/home/example-cup.mp4",
    poster: "/home/example-cup.jpg",
    name: "Stoneware cup",
    meta: "Product ad · 15 sec · Bahasa Melayu",
    stylePrompt:
      "Create a 15-second launch video for my new ceramic coffee cup. Warm morning light, calm Bahasa Melayu, product stays the hero.",
  },
  {
    id: "raya",
    src: "/home/example-campaign.mp4",
    poster: "/home/example-campaign.jpg",
    name: "Raya colour story",
    meta: "Campaign look · 15 sec · Product film",
    stylePrompt:
      "Promote my Raya collection. Warm festive lighting, close product beauty shots, and a short Bahasa Melayu invitation to shop.",
  },
  {
    id: "fnb",
    src: "/home/example-fnb.mp4",
    poster: "/home/example-fnb.jpg",
    name: "Handmade clay mug",
    meta: "Food & beverage · 15 sec · Bahasa Melayu",
    stylePrompt:
      "Create a food and beverage promotion. Show the drinkware in a real morning moment, Bahasa Melayu captions, warm and inviting.",
  },
  {
    id: "explain",
    src: "/home/example-explainer.mp4",
    poster: "/home/example-explainer.jpg",
    name: "Compact air fryer",
    meta: "Business explainer · 15 sec · Bahasa Melayu",
    stylePrompt:
      "Create a Bahasa Melayu explainer for this product. Show why it fits a small kitchen, keep the product recognisable, end with a clear next step.",
  },
] as const;

export function emptyHomeDraft(): HomeDraft {
  return {
    prompt: "",
    aspect: "9:16",
    duration: 15,
    photos: [],
    savedAt: 0,
  };
}

export function parseHomeDraft(raw: string | null): HomeDraft | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<HomeDraft>;
    if (typeof parsed.prompt !== "string") return null;
    const aspect = HOME_FORMATS.some((item) => item.id === parsed.aspect)
      ? (parsed.aspect as HomeAspect)
      : "9:16";
    const duration = HOME_DURATIONS.includes(parsed.duration as HomeDuration)
      ? (parsed.duration as HomeDuration)
      : 15;
    const photos = Array.isArray(parsed.photos)
      ? parsed.photos.filter(
          (item): item is HomePhoto =>
            Boolean(item && typeof item.dataUrl === "string" && item.dataUrl.startsWith("data:image/")),
        )
      : [];
    return {
      prompt: parsed.prompt,
      aspect,
      duration,
      photos,
      intent: typeof parsed.intent === "string" ? parsed.intent : undefined,
      savedAt: Number(parsed.savedAt) || 0,
    };
  } catch {
    return null;
  }
}

export function readHomeDraft(): HomeDraft | null {
  if (typeof window === "undefined") return null;
  return parseHomeDraft(sessionStorage.getItem(HOME_DRAFT_KEY));
}

export function writeHomeDraft(draft: HomeDraft) {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(
    HOME_DRAFT_KEY,
    JSON.stringify({ ...draft, savedAt: Date.now() } satisfies HomeDraft),
  );
}

export function clearHomeDraft() {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(HOME_DRAFT_KEY);
}

export function hasHomeDraft(draft: HomeDraft | null | undefined): boolean {
  return Boolean(draft && (draft.prompt.trim() || draft.photos.length));
}

export function studioEntryPath() {
  return "/brand/studio?from=home";
}

export function registerForStudioPath() {
  return `/brand/register?next=${encodeURIComponent(studioEntryPath())}`;
}

export function loginForStudioPath() {
  return `/brand/login?next=${encodeURIComponent(studioEntryPath())}`;
}

export async function filesToHomePhotos(files: File[], limit = 4): Promise<HomePhoto[]> {
  const chosen = files.slice(0, limit);
  const photos: HomePhoto[] = [];
  for (const file of chosen) {
    if (!file.type.startsWith("image/")) continue;
    photos.push({
      name: file.name || "product.jpg",
      type: "image/jpeg",
      dataUrl: await compressImage(file),
    });
  }
  return photos;
}

export async function homePhotosToFiles(photos: HomePhoto[]): Promise<File[]> {
  const files: File[] = [];
  for (const photo of photos) {
    const response = await fetch(photo.dataUrl);
    const blob = await response.blob();
    files.push(new File([blob], photo.name || "product.jpg", { type: photo.type || blob.type || "image/jpeg" }));
  }
  return files;
}

function compressImage(file: File, maxSize = 1280, quality = 0.72): Promise<string> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const url = URL.createObjectURL(file);
    image.onload = () => {
      const scale = Math.min(1, maxSize / Math.max(image.width, image.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.width * scale));
      canvas.height = Math.max(1, Math.round(image.height * scale));
      const context = canvas.getContext("2d");
      if (!context) {
        URL.revokeObjectURL(url);
        reject(new Error("Could not read this image."));
        return;
      }
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/jpeg", quality));
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read this image."));
    };
    image.src = url;
  });
}

export function draftToBriefSeed(draft: HomeDraft) {
  const prompt = draft.prompt.trim();
  const firstLine = prompt.split("\n")[0]?.slice(0, 180) || "Show the product clearly.";
  return {
    prompt,
    duration: draft.duration,
    platform: draft.aspect === "16:9" ? "facebook" : draft.aspect === "1:1" ? "instagram" : "tiktok",
    objective: "buy",
    customer: "Malaysian shoppers watching on TikTok, Reels and Shorts",
    main_benefit: firstLine,
    must_remain_exact: ["product_appearance", "logo", "packaging", "product_name"],
  };
}
