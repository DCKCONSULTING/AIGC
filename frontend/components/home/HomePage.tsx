"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth";
import {
  filesToHomePhotos,
  loginForStudioPath,
  registerForStudioPath,
  studioEntryPath,
  writeHomeDraft,
  type HomeAspect,
  type HomeDuration,
} from "@/lib/home";
import { canAccessBrand } from "@/lib/paths";

import { CreationPanel } from "./CreationPanel";
import { PublicFooter } from "./PublicFooter";
import { PublicHeader } from "./PublicHeader";

const PLACEHOLDER =
  "Create an energetic 15-second product video for busy Malaysian families. Show crispy fries with less oil, use a friendly local host, and end with “Makan sedap, senang je.”";

type PhotoItem = { file: File; url: string };

const EXAMPLES = [
  {
    id: "air",
    media: "media-air",
    badge: "Product demo",
    title: "Clean product close-up",
    meta: "15 sec · BM",
    src: "/home/example-explainer.mp4",
    poster: "/misa-design/air-crisp-lifestyle.jpg",
    prompt:
      "Create a 15-second product demo for a compact air fryer. Show crispy fries with less oil, friendly Bahasa Malaysia captions, and a clear shop-now close.",
  },
  {
    id: "cup",
    media: "media-cup",
    badge: "Lifestyle story",
    title: "Morning routine",
    meta: "30 sec · English",
    src: "/home/example-cup.mp4",
    poster: "/misa-design/terra-cup-lifestyle.jpg",
    prompt:
      "Create a 30-second morning lifestyle story for a ceramic cup. Warm light, calm English voice, product stays the hero.",
  },
  {
    id: "social",
    media: "media-social",
    badge: "Creator format",
    title: "Problem to product",
    meta: "45 sec · BM + English",
    src: "/home/example-fnb.mp4",
    poster: "/misa-design/misa-reference.png",
    prompt:
      "Create a 45-second problem-to-product video. Open with a busy-day hook, show the product solving it, mix Bahasa Malaysia and English.",
  },
] as const;

export function HomePage() {
  const router = useRouter();
  const { user, ready, workspace, actingAccount } = useAuth();
  const [prompt, setPrompt] = useState("");
  const [photos, setPhotos] = useState<PhotoItem[]>([]);
  const [aspect, setAspect] = useState<HomeAspect>("9:16");
  const [duration, setDuration] = useState<HomeDuration>(15);
  const [locale, setLocale] = useState<"en" | "bm">("en");
  const [gate, setGate] = useState(false);
  const [playing, setPlaying] = useState<string | null>(null);
  const [category, setCategory] = useState("Home & Kitchen");
  const [previewReady, setPreviewReady] = useState(false);

  const producer = canAccessBrand(user, workspace, actingAccount);
  const bm = locale === "bm";
  const photosRef = useRef(photos);

  useEffect(() => {
    photosRef.current = photos;
  }, [photos]);

  useEffect(() => () => photosRef.current.forEach((photo) => URL.revokeObjectURL(photo.url)), []);

  function focusCreate() {
    document.getElementById("free-trial")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function persistDraft() {
    const storedPhotos = await filesToHomePhotos(photos.map((item) => item.file));
    const draft = {
      prompt: prompt.trim() || PLACEHOLDER,
      aspect,
      duration,
      photos: storedPhotos,
      savedAt: Date.now(),
    };
    writeHomeDraft(draft);
    return draft;
  }

  async function generate() {
    try {
      await persistDraft();
    } catch {
      writeHomeDraft({
        prompt: prompt.trim() || PLACEHOLDER,
        aspect,
        duration,
        photos: [],
        savedAt: Date.now(),
      });
    }
    setPreviewReady(true);
    if (ready && producer) {
      router.push(studioEntryPath());
      return;
    }
    setGate(true);
  }

  const previewPhoto = photos[0]?.url;

  return (
    <div className="misa flex min-h-full flex-1 flex-col">
      <a
        href="#free-trial"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-xl focus:bg-primary focus:px-4 focus:py-2 focus:text-white"
      >
        Skip to creation
      </a>
      <PublicHeader onCreate={focusCreate} />

      <main className="public-landing flex-1">
        <section className="misa-hero" aria-labelledby="hero-title">
          <div className="hero-copy-block">
            <div className="malaysia-pill">
              <span aria-hidden="true">🇲🇾</span>
              {bm ? "15 saat pertama kami belanja" : "Your first 15 seconds are on us"}
            </div>
            <h1 id="hero-title">
              {bm ? (
                <>
                  Tengok produk anda
                  <br />
                  jadi <span>video 15 saat.</span> Percuma.
                </>
              ) : (
                <>
                  See your product
                  <br />
                  as a <span>15-sec video.</span> Free.
                </>
              )}
            </h1>
            <p>
              {bm
                ? "Pilih mana-mana produk e-dagang, beritahu MiSa sudut anda, dan tengok video menegak pertama anda terbentuk."
                : "Choose any e-commerce product, tell MiSa your angle, and watch your first vertical video take shape."}
            </p>
            <div className="hero-ctas">
              <button type="button" className="hero-create" onClick={focusCreate}>
                {bm ? "Cuba sekarang" : "Try it now"} <span aria-hidden="true">↓</span>
              </button>
              <a href="#examples" className="hero-watch inline-flex items-center justify-center">
                <span aria-hidden="true">▶</span> {bm ? "Tonton contoh" : "Watch examples"}
              </a>
            </div>
            <div className="language-row">
              <span aria-hidden="true">◎</span> {bm ? "Tanpa kad" : "No card needed"} <i>·</i> {aspect}{" "}
              <i>·</i> BM + English
            </div>
          </div>

          <div id="free-trial" className="free-trial-card" aria-label="Create a free 15-second video mock-up">
            <div className="trial-accent" aria-hidden="true" />
            <CreationPanel
              prompt={prompt}
              onPrompt={setPrompt}
              photos={photos}
              onPhotos={setPhotos}
              aspect={aspect}
              duration={duration}
              onAspect={setAspect}
              onDuration={setDuration}
              onGenerate={generate}
              heading={bm ? "Tunjuk produk anda." : "Show us your product."}
              category={category}
              onCategory={setCategory}
            />
            <aside className={`trial-preview ${previewReady ? "ready" : ""}`} aria-label="15-second vertical video preview">
              <div className="trial-preview-top">
                <span>LIVE PREVIEW</span>
                <strong>{aspect}</strong>
              </div>
              <div
                className={`trial-video-frame ${previewPhoto ? "has-photo" : ""}`}
                style={
                  previewPhoto
                    ? {
                        backgroundImage: `linear-gradient(180deg,rgba(5,10,28,.03) 34%,rgba(6,10,28,.18) 61%,rgba(5,7,18,.82) 100%),url("${previewPhoto}")`,
                      }
                    : undefined
                }
              >
                <div className="trial-scene-label">{category.toUpperCase()}</div>
                <div className="trial-video-copy">
                  <small>{bm ? "Hari sibuk?" : "Busy day?"}</small>
                  <strong>
                    Crispy dinner.
                    <br />
                    Kurang minyak.
                  </strong>
                </div>
                <div className="trial-price">
                  15 min
                  <br />
                  <span>to makan</span>
                </div>
                <button type="button" className="trial-play" aria-label="Play video preview">
                  ▶
                </button>
                <div className="trial-caption">“Makan sedap, senang je.”</div>
                <div className="trial-watermark">MiSa mock-up</div>
              </div>
              <div className="trial-progress">
                <span>Your {duration}-sec story</span>
                <div>
                  <i />
                </div>
                <time>00:{String(duration).padStart(2, "0")}</time>
              </div>
              <div className="trial-scenes">
                <span className="active">Hook</span>
                <span>Demo</span>
                <span>Benefit</span>
                <span>CTA</span>
              </div>
            </aside>
          </div>
        </section>

        <section id="how" className="public-section how-section">
          <div className="public-kicker">{bm ? "Dari produk ke siaran" : "From product to post"}</div>
          <h2>
            {bm ? "Semua yang video produk anda perlukan." : "Everything your product video needs."}
            <br />
            <span>{bm ? "Tanpa perkara yang anda perlu belajar." : "Nothing you have to learn."}</span>
          </h2>
          <div className="how-grid">
            <article>
              <div className="how-icon">01</div>
              <h3>{bm ? "Pilih mana-mana produk" : "Choose any product"}</h3>
              <p>
                {bm
                  ? "Pilih kategori e-dagang, ambil dari katalog anda atau muat naik produk baharu."
                  : "Select an e-commerce category, pick from your catalogue or upload a new product."}
              </p>
            </article>
            <article>
              <div className="how-icon">02</div>
              <h3>{bm ? "Beritahu apa yang anda mahu" : "Say what you want"}</h3>
              <p>
                {bm
                  ? "Tulis secara semula jadi. Beritahu MiSa audiens, kelebihan dan tindakan—tanpa kepakaran prompt."
                  : "Write naturally. Tell MiSa the audience, benefit and action—no prompt expertise needed."}
              </p>
            </article>
            <article>
              <div className="how-icon">03</div>
              <h3>{bm ? "Tengok mock-up anda" : "Watch your mock-up"}</h3>
              <p>
                {bm
                  ? "Dapat satu konsep menegak 15 saat percuma, kemudian log masuk hanya jika anda mahu teruskan."
                  : "Get one free 15-second vertical concept, then sign in only if you want to take it further."}
              </p>
            </article>
          </div>
        </section>

        <section id="examples" className="public-section examples-section">
          <div className="examples-head">
            <div>
              <div className="public-kicker">{bm ? "Dibuat dengan MiSa" : "Made with MiSa"}</div>
              <h2>{bm ? "Satu produk. Banyak cerita." : "One product. Many stories."}</h2>
            </div>
            <button type="button" className="text-link" onClick={focusCreate}>
              {bm ? "Cuba 15 saat percuma →" : "Try 15 sec free →"}
            </button>
          </div>
          <div className="example-grid">
            {EXAMPLES.map((item) => (
              <article key={item.id} className="example-card">
                <div className={`example-media ${item.media}`}>
                  {playing === item.id ? (
                    <video src={item.src} poster={item.poster} autoPlay muted playsInline controls />
                  ) : null}
                  <span>{item.badge}</span>
                  <button
                    type="button"
                    aria-label={`Play ${item.title}`}
                    onClick={() => {
                      setPlaying(item.id);
                      setPrompt(item.prompt);
                    }}
                  >
                    ▶
                  </button>
                </div>
                <h3>{item.title}</h3>
                <p>{item.meta}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="pricing" className="public-section public-price-strip">
          <div>
            <div className="public-kicker">{bm ? "Mula mencipta" : "Start creating"}</div>
            <h2>{bm ? "Produk pertama anda layak dapat video yang lebih baik." : "Your first product deserves a better video."}</h2>
            <p>{bm ? "Bina cerita lengkap dalam satu ruang kerja berpandu." : "Build the complete story in one guided workspace."}</p>
          </div>
          <div className="price-strip-actions">
            <button type="button" className="hero-create" onClick={focusCreate}>
              {bm ? "Cuba 15 saat percuma →" : "Try 15 sec free →"}
            </button>
            <Link href="/brand/register" className="hero-watch inline-flex items-center justify-center">
              {bm ? "Cipta akaun" : "Create account"}
            </Link>
          </div>
        </section>
      </main>

      <PublicFooter locale={locale} onLocale={setLocale} />

      {gate ? (
        <div className="misa-gate fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
          <div className="misa-gate-card w-full max-w-md p-8">
            <p className="trial-kicker">Your idea is ready.</p>
            <h2 className="misa-display mt-3 text-3xl">Create an account to generate the video.</h2>
            <p className="mt-3 text-sm leading-6 text-muted">
              Your prompt, photos and format stay saved. After you sign in, MiSa opens Studio with everything you entered.
            </p>
            <div className="mt-7 flex flex-col gap-3">
              <Link
                href={registerForStudioPath()}
                className="public-create inline-flex h-12 items-center justify-center"
              >
                Create account
              </Link>
              <Link
                href={loginForStudioPath()}
                className="hero-watch inline-flex h-12 items-center justify-center"
              >
                Log in
              </Link>
              <button type="button" onClick={() => setGate(false)} className="text-sm text-muted">
                Keep editing
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
