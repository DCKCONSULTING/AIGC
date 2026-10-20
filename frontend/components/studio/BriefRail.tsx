"use client";

import type { Brand, Product } from "@/lib/api";
import type { CreativeBriefForm } from "@/lib/director";
import { OBJECTIVES, PLATFORM_OPTIONS } from "@/lib/director";
import { genderLabel, generationFormatNote, languageLabel, styleLabel } from "@/lib/studio";

export function BriefRail({
  product,
  brand,
  brief,
  language,
  style,
  gender,
  characterName,
  onSelectProduct,
}: {
  product: Product | null;
  brand?: Brand | null;
  brief: CreativeBriefForm;
  language: string;
  style: string;
  gender: string;
  characterName?: string;
  onSelectProduct?: () => void;
}) {
  const objective = OBJECTIVES.find((item) => item.id === brief.objective)?.label;
  const platform = PLATFORM_OPTIONS.find((item) => item.id === brief.platform)?.label;
  const story = [objective && `Ask viewers to ${objective.toLowerCase()}`, brief.customer, brief.main_benefit]
    .filter(Boolean)
    .join(". ");
  const prompt = brief.legacy_instructions?.trim() || story;

  return (
    <aside className="min-w-0 rounded-2xl border border-line bg-card p-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-primary">Project / Brief</p>

      <div className="mt-4">
        <p className="text-[11px] uppercase tracking-[0.14em] text-muted">Product</p>
        {product ? (
          <div className="mt-2 flex items-start gap-3">
            {product.images[0] ? (
              <img src={product.images[0].url} alt="" className="h-12 w-12 rounded-lg object-cover" />
            ) : (
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-[#f1f8ff] text-[10px] text-muted">
                No photo
              </div>
            )}
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{product.name}</p>
              <p className="truncate text-xs text-muted">
                {product.brand_name || brand?.name || "Brand"}
                {product.price ? ` · RM ${product.price}` : ""}
              </p>
            </div>
          </div>
        ) : (
          <div className="mt-2 rounded-xl border border-dashed border-[#ffd0e2] bg-[#f7faff] px-3 py-3">
            <p className="text-sm font-medium">Product required</p>
            <p className="mt-1 text-xs text-muted">MISA needs a product before it can generate.</p>
            {onSelectProduct ? (
              <button
                type="button"
                onClick={onSelectProduct}
                className="mt-3 h-9 rounded-full bg-primary px-4 text-xs font-medium text-white"
              >
                Select product
              </button>
            ) : null}
          </div>
        )}
      </div>

      <dl className="mt-4 grid gap-3 text-sm">
        <div>
          <dt className="text-[11px] uppercase tracking-[0.14em] text-muted">Prompt / Story</dt>
          <dd className="mt-1 whitespace-pre-wrap text-[13px] leading-5">
            {prompt || "No story yet. Add the viewer action, customer, and main benefit."}
          </dd>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <dt className="text-[11px] uppercase tracking-[0.14em] text-muted">Format</dt>
            <dd className="mt-1 font-medium">9:16</dd>
          </div>
          <div>
            <dt className="text-[11px] uppercase tracking-[0.14em] text-muted">Duration</dt>
            <dd className="mt-1 font-medium">{brief.duration || 15} sec</dd>
          </div>
        </div>
        <p className="text-[11px] leading-4 text-muted">{generationFormatNote()}</p>
        {platform && platform !== "Any platform" ? (
          <div>
            <dt className="text-[11px] uppercase tracking-[0.14em] text-muted">Platform preference</dt>
            <dd className="mt-1">{platform}</dd>
          </div>
        ) : null}
        {brief.original_price || brief.offer_price || brief.offer_text ? (
          <div>
            <dt className="text-[11px] uppercase tracking-[0.14em] text-muted">Price / offer</dt>
            <dd className="mt-1">
              {[
                brief.original_price ? `Original ${brief.original_price}` : "",
                brief.offer_price ? `Offer ${brief.offer_price}` : "",
                brief.offer_text,
              ]
                .filter(Boolean)
                .join(" · ")}
            </dd>
          </div>
        ) : null}
      </dl>

      <div className="mt-4 border-t border-line pt-3">
        <p className="text-[11px] uppercase tracking-[0.14em] text-muted">Character</p>
        <p className="mt-1 text-sm font-medium">{characterName || "No character selected"}</p>
      </div>

      <details className="mt-4 border-t border-line pt-3">
        <summary className="cursor-pointer text-sm font-medium">Audio & captions</summary>
        <dl className="mt-3 grid gap-3 text-sm">
          <div>
            <dt className="text-[11px] uppercase tracking-[0.14em] text-muted">Language</dt>
            <dd className="mt-1">{languageLabel(language)}</dd>
          </div>
          <div>
            <dt className="text-[11px] uppercase tracking-[0.14em] text-muted">Preferred voice</dt>
            <dd className="mt-1">
              {styleLabel(style)} · {genderLabel(gender)}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] uppercase tracking-[0.14em] text-muted">Captions</dt>
            <dd className="mt-1">{languageLabel(language)}</dd>
          </div>
        </dl>
      </details>

      {brand ? (
        <div className="mt-4 border-t border-line pt-3">
          <p className="text-[11px] uppercase tracking-[0.14em] text-muted">Brand</p>
          <p className="mt-1 text-sm font-medium">{brand.name}</p>
          {brand.description ? <p className="mt-1 line-clamp-3 text-xs text-muted">{brand.description}</p> : null}
        </div>
      ) : null}
    </aside>
  );
}
