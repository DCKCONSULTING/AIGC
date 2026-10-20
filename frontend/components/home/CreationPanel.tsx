"use client";

import { FormEvent, useRef, useState } from "react";

import {
  HOME_DURATIONS,
  HOME_FORMATS,
  type HomeAspect,
  type HomeDuration,
} from "@/lib/home";

type PhotoItem = { file: File; url: string };

const CATEGORIES = [
  "Home & Kitchen",
  "Beauty & Personal Care",
  "Fashion",
  "Food & Beverage",
  "Electronics",
  "Baby & Kids",
  "Pet Supplies",
  "Sports & Outdoors",
  "Automotive",
  "Other",
];

const PRODUCTS: Record<string, string[]> = {
  "Home & Kitchen": ["Penang Air Crisp", "Storii food container", "Add my own product…"],
  "Beauty & Personal Care": ["Luma serum", "Add my own product…"],
  Fashion: ["Weekend tote", "Add my own product…"],
  "Food & Beverage": ["Kopi pagi blend", "Add my own product…"],
  Electronics: ["Pocket charger", "Add my own product…"],
  "Baby & Kids": ["Soft sip cup", "Add my own product…"],
  "Pet Supplies": ["Slow feeder bowl", "Add my own product…"],
  "Sports & Outdoors": ["Trail bottle", "Add my own product…"],
  Automotive: ["Cabin organiser", "Add my own product…"],
  Other: ["Add my own product…"],
};

const STARTERS = [
  { label: "Premium", text: "Make it feel premium" },
  { label: "BM santai", text: "Use a casual Bahasa Malaysia tone" },
  { label: "Shop now CTA", text: "End with a clear shop-now call to action" },
];

export function CreationPanel({
  prompt,
  onPrompt,
  photos,
  onPhotos,
  aspect,
  duration,
  onAspect,
  onDuration,
  onGenerate,
  pending = false,
  variant = "hero",
  heading,
  category,
  onCategory,
}: {
  prompt: string;
  onPrompt: (value: string) => void;
  photos: PhotoItem[];
  onPhotos: (next: PhotoItem[]) => void;
  aspect: HomeAspect;
  duration: HomeDuration;
  onAspect: (value: HomeAspect) => void;
  onDuration: (value: HomeDuration) => void;
  onGenerate: () => void;
  pending?: boolean;
  variant?: "hero" | "final";
  heading?: string;
  category?: string;
  onCategory?: (value: string) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [product, setProduct] = useState("Penang Air Crisp");
  const [dragging, setDragging] = useState(false);
  const selectedCategory = category || "Home & Kitchen";
  const products = PRODUCTS[selectedCategory] || PRODUCTS.Other;

  function addFiles(list: FileList | File[]) {
    const incoming = Array.from(list).filter((file) => file.type.startsWith("image/"));
    if (!incoming.length) return;
    const next = [...photos];
    for (const file of incoming) {
      if (next.length >= 4) break;
      next.push({ file, url: URL.createObjectURL(file) });
    }
    onPhotos(next);
  }

  function removePhoto(index: number) {
    const target = photos[index];
    if (target) URL.revokeObjectURL(target.url);
    onPhotos(photos.filter((_, current) => current !== index));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    onGenerate();
  }

  function addStarter(text: string) {
    const next = `${prompt.trim()} ${text}.`.trim().slice(0, 300);
    onPrompt(next);
  }

  const compact = variant === "final";

  return (
    <form
      onSubmit={submit}
      className="trial-form"
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        addFiles(event.dataTransfer.files);
      }}
    >
      <div className="trial-heading">
        <div>
          <span className="trial-kicker">Free video mock-up</span>
          <h2>{heading || "Show us your product."}</h2>
        </div>
        <span className="free-badge">FREE · {duration} SEC</span>
      </div>

      <div className="trial-step-label">
        <b>1</b>
        <span>Choose a product</span>
      </div>
      <div className="trial-selects">
        <label>
          Category
          <select
            aria-label="Product category"
            value={selectedCategory}
            onChange={(event) => {
              const next = event.target.value;
              onCategory?.(next);
              const first = (PRODUCTS[next] || PRODUCTS.Other)[0];
              setProduct(first);
            }}
          >
            {CATEGORIES.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          Product
          <select
            aria-label="Product"
            value={product}
            onChange={(event) => setProduct(event.target.value)}
          >
            {products.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
      </div>

      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        multiple
        className="sr-only"
        onChange={(event) => {
          if (event.target.files) addFiles(event.target.files);
          event.target.value = "";
        }}
      />
      <button
        type="button"
        className="trial-upload"
        style={dragging ? { borderColor: "#0874f9", background: "#f2f8ff" } : undefined}
        onClick={() => fileRef.current?.click()}
      >
        <span>＋</span>
        <span>
          <strong>Upload your product</strong>
          <small>Photo, product link or marketplace listing</small>
        </span>
      </button>

      {photos.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {photos.map((photo, index) => (
            <div key={photo.url} className="relative h-14 w-14 overflow-hidden rounded-xl">
              <img src={photo.url} alt="" className="h-full w-full object-cover" />
              <button
                type="button"
                onClick={() => removePhoto(index)}
                className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-[#09132f] text-[10px] text-white"
                aria-label="Remove image"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      ) : null}

      <div className="trial-step-label">
        <b>2</b>
        <span>Tell MiSa what to create</span>
      </div>
      <label className="trial-prompt-label" htmlFor="trialPrompt">
        Your prompt
      </label>
      <div className="trial-prompt-wrap">
        <textarea
          id="trialPrompt"
          value={prompt}
          maxLength={300}
          onChange={(event) => onPrompt(event.target.value)}
          placeholder="Create an energetic 15-second product video for busy Malaysian families. Show crispy fries with less oil, use a friendly local host, and end with “Makan sedap, senang je.”"
          rows={compact ? 4 : 5}
        />
        <span className="trial-prompt-count">{prompt.length} / 300</span>
      </div>
      <div className="prompt-starters" aria-label="Prompt suggestions">
        {STARTERS.map((item) => (
          <button key={item.label} type="button" onClick={() => addStarter(item.text)}>
            {item.label}
          </button>
        ))}
      </div>

      <div className="trial-settings">
        {HOME_FORMATS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={aspect === item.id ? "active" : undefined}
            onClick={() => onAspect(item.id)}
          >
            ▯ {item.id} {item.id === "9:16" ? "vertical" : item.label}
          </button>
        ))}
        {HOME_DURATIONS.map((item) => (
          <button
            key={item}
            type="button"
            className={duration === item ? "active" : undefined}
            onClick={() => onDuration(item)}
          >
            ◷ {item} seconds
          </button>
        ))}
        <span>文 BM + English</span>
      </div>

      <button type="submit" disabled={pending} className={`trial-generate ${pending ? "generating" : ""}`}>
        <span>✦</span>
        <strong>{pending ? "Building your 15-sec story…" : "Generate my free video"}</strong>
        <em>{pending ? "About 1 min" : "No credit card"}</em>
      </button>
      <p className="trial-note">
        One free watermarked mock-up per business. Sign in to edit, export or create more.
      </p>
    </form>
  );
}

export function revokePhotos(photos: PhotoItem[]) {
  photos.forEach((photo) => URL.revokeObjectURL(photo.url));
}
