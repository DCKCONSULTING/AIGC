"use client";

import { MUST_REMAIN_OPTIONS, OBJECTIVES, PLATFORM_OPTIONS, type CreativeBriefForm } from "@/lib/director";
import { DURATION_OPTIONS } from "@/lib/studio";
import { ChoiceButton } from "./ui";

export function CreativeBriefWizard({
  brief,
  onChange,
}: {
  brief: CreativeBriefForm;
  onChange: (next: CreativeBriefForm) => void;
}) {
  function toggleRemain(id: string) {
    const current = brief.must_remain_exact.includes(id)
      ? brief.must_remain_exact.filter((item) => item !== id)
      : [...brief.must_remain_exact, id];
    onChange({ ...brief, must_remain_exact: current });
  }

  return (
    <div className="grid gap-8">
      <div>
        <h2 className="font-serif text-3xl">What do you want viewers to do? <span className="text-[#b71958]">*</span></h2>
        <p className="mt-2 text-sm text-muted">Pick one main action. We will write the video around it.</p>
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {OBJECTIVES.map((item) => (
            <ChoiceButton
              key={item.id}
              selected={brief.objective === item.id}
              title={item.label}
              hint={item.hint}
              onClick={() => onChange({ ...brief, objective: item.id })}
            />
          ))}
        </div>
      </div>

      <label className="block text-sm">
        Who is your customer? <span className="text-[#b71958]">*</span>
        <input
          value={brief.customer}
          onChange={(event) => onChange({ ...brief, customer: event.target.value })}
          placeholder="Example: Busy Malaysian parents who want quick healthy meals."
          className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
        />
      </label>

      <label className="block text-sm">
        What is the main product benefit? <span className="text-[#b71958]">*</span>
        <input
          value={brief.main_benefit}
          onChange={(event) => onChange({ ...brief, main_benefit: event.target.value })}
          placeholder="Example: Cooks family meals quickly with less oil."
          className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
        />
      </label>

      <div>
        <h2 className="font-serif text-3xl">What offer or price should appear?</h2>
        <p className="mt-2 text-sm text-muted">
          Optional. We will only show prices you type here or that are already on the product.
        </p>
        <div className="mt-5 grid gap-4 md:grid-cols-3">
          <label className="block text-sm">
            Original price
            <input
              value={brief.original_price}
              onChange={(event) => onChange({ ...brief, original_price: event.target.value })}
              placeholder="RM189"
              className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
            />
          </label>
          <label className="block text-sm">
            Offer price
            <input
              value={brief.offer_price}
              onChange={(event) => onChange({ ...brief, offer_price: event.target.value })}
              placeholder="RM169"
              className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
            />
          </label>
          <label className="block text-sm">
            Discount / offer text
            <input
              value={brief.offer_text}
              onChange={(event) => onChange({ ...brief, offer_text: event.target.value })}
              placeholder="Optional"
              className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
            />
          </label>
        </div>
      </div>

      <div>
        <h2 className="font-serif text-3xl">What must remain exactly the same?</h2>
        <p className="mt-2 text-sm text-muted">Lock the facts the AI must not redesign.</p>
        <div className="mt-5 flex flex-wrap gap-2">
          {MUST_REMAIN_OPTIONS.map((item) => {
            const selected = brief.must_remain_exact.includes(item.id);
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => toggleRemain(item.id)}
                className={`h-11 rounded-full border px-4 text-sm ${
                  selected ? "border-gold bg-gold/15" : "border-line"
                }`}
              >
                {selected ? "🔒 " : ""}
                {item.label}
              </button>
            );
          })}
        </div>
      </div>

      <label className="block text-sm">
        Is there anything the video must not show?
        <textarea
          rows={3}
          value={brief.must_not_show}
          onChange={(event) => onChange({ ...brief, must_not_show: event.target.value })}
          placeholder="Optional. Example: Do not show children using the product."
          className="mt-2 w-full rounded-2xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
        />
      </label>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className="text-sm font-medium">Length</p>
          <div className="mt-3 flex flex-wrap gap-3">
            {DURATION_OPTIONS.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => onChange({ ...brief, duration: value })}
                className={`h-12 min-w-24 rounded-full border px-5 text-sm ${
                  brief.duration === value ? "border-gold bg-gold/15" : "border-line"
                }`}
              >
                {value} sec
              </button>
            ))}
          </div>
        </div>
        <label className="block text-sm">
          Platform
          <select
            value={brief.platform}
            onChange={(event) => onChange({ ...brief, platform: event.target.value })}
            className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
          >
            {PLATFORM_OPTIONS.map((item) => (
              <option key={item.id || "any"} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="block text-sm">
        Background / location
        <input
          value={brief.location}
          onChange={(event) => onChange({ ...brief, location: event.target.value })}
          placeholder="Example: a bright modern kitchen, or a home living room."
          className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
        />
      </label>

      <label className="block text-sm">
        Extra instruction
        <span className="ml-2 font-normal text-muted">Optional</span>
        <textarea
          rows={4}
          value={brief.legacy_instructions}
          onChange={(event) => onChange({ ...brief, legacy_instructions: event.target.value })}
          placeholder="Optional. If you add notes, we will use them when writing the story."
          className="mt-2 w-full rounded-2xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
        />
      </label>
    </div>
  );
}
