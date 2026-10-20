"use client";

import { FormEvent, useState } from "react";

import { api, endpoints, type Brand, type Product } from "@/lib/api";

const emptyForm = {
  brand: "",
  name: "",
  description: "",
  product_url: "",
  price: "",
  commission: "0",
  variants: "",
  dimensions: "",
  materials: "",
  offer: "",
  offer_expiry: "",
  approved_claims: "",
};

type StudioProductModalProps = {
  token: string | null;
  brands: Brand[];
  defaultBrand: string;
  onClose: () => void;
  onSaved: (product: Product) => void;
};

export function StudioProductModal({
  token,
  brands,
  defaultBrand,
  onClose,
  onSaved,
}: StudioProductModalProps) {
  const [form, setForm] = useState({ ...emptyForm, brand: defaultBrand });
  const [photos, setPhotos] = useState<File[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    setError("");
    setPending(true);
    try {
      const payload = new FormData();
      payload.append("brand", form.brand);
      payload.append("name", form.name);
      payload.append("description", form.description);
      payload.append("product_url", form.product_url);
      payload.append("price", form.price);
      payload.append("commission", form.commission || "0");
      payload.append(
        "variants",
        JSON.stringify(
          form.variants
            .split(",")
            .map((part) => part.trim())
            .filter(Boolean),
        ),
      );
      payload.append("dimensions", form.dimensions);
      payload.append("materials", form.materials);
      payload.append("offer", form.offer);
      payload.append("offer_expiry", form.offer_expiry);
      payload.append(
        "approved_claims",
        JSON.stringify(
          form.approved_claims
            .split(",")
            .map((part) => part.trim())
            .filter(Boolean),
        ),
      );
      photos.forEach((photo) => payload.append("photos", photo));
      const created = await api<Product>(endpoints.brands.products, {
        method: "POST",
        token,
        body: payload,
      });
      onSaved(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save product.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/30"
        aria-label="Close"
        onClick={() => !pending && onClose()}
      />
      <form
        onSubmit={onSubmit}
        className="relative max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-line bg-card p-6 shadow-lg"
      >
        <h2 className="font-serif text-2xl">New product</h2>
        <p className="mt-1 text-sm text-muted">Add the details this video should sell.</p>
        {error ? (
          <p className="mt-4 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </p>
        ) : null}
        <div className="mt-5 grid gap-4">
          <label className="block text-sm">
            Brand
            <select
              required
              value={form.brand}
              onChange={(event) => setForm({ ...form, brand: event.target.value })}
              className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
            >
              <option value="" disabled>
                Select a brand
              </option>
              {brands.map((brand) => (
                <option key={brand.id} value={brand.id}>
                  {brand.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            Photos
            <input
              type="file"
              accept="image/*"
              multiple
              className="mt-2 w-full text-sm"
              onChange={(event) => setPhotos(Array.from(event.target.files ?? []))}
            />
          </label>
          <label className="block text-sm">
            Product name
            <input
              required
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
            />
          </label>
          <label className="block text-sm">
            Description
            <textarea
              required
              rows={3}
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
              className="mt-2 w-full rounded-xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
            />
          </label>
          <label className="block text-sm">
            Product URL
            <input
              type="url"
              value={form.product_url}
              onChange={(event) => setForm({ ...form, product_url: event.target.value })}
              placeholder="https://shop.example.com/product"
              className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
            />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm">
              Price
              <input
                required
                type="number"
                min="0"
                step="0.01"
                value={form.price}
                onChange={(event) => setForm({ ...form, price: event.target.value })}
                className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
            <label className="block text-sm">
              Commission (%)
              <input
                type="number"
                min="0"
                max="100"
                step="0.01"
                value={form.commission}
                onChange={(event) => setForm({ ...form, commission: event.target.value })}
                className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
          </div>
          <label className="block text-sm">
            Variants
            <input
              value={form.variants}
              onChange={(event) => setForm({ ...form, variants: event.target.value })}
              placeholder="30ml, 50ml"
              className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
            />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm">
              Dimensions
              <input
                value={form.dimensions}
                onChange={(event) => setForm({ ...form, dimensions: event.target.value })}
                className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
            <label className="block text-sm">
              Materials
              <input
                value={form.materials}
                onChange={(event) => setForm({ ...form, materials: event.target.value })}
                className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm">
              Offer
              <input
                value={form.offer}
                onChange={(event) => setForm({ ...form, offer: event.target.value })}
                className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
            <label className="block text-sm">
              Offer expiry
              <input
                type="date"
                value={form.offer_expiry}
                onChange={(event) => setForm({ ...form, offer_expiry: event.target.value })}
                className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
          </div>
          <label className="block text-sm">
            Approved claims
            <input
              value={form.approved_claims}
              onChange={(event) => setForm({ ...form, approved_claims: event.target.value })}
              placeholder="hydrating, lightweight"
              className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
            />
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={pending}
            className="h-11 rounded-full border border-line px-5 text-sm hover:bg-black/5"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={pending}
            className="h-11 rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep disabled:opacity-60"
          >
            {pending ? "Saving…" : "Save product"}
          </button>
        </div>
      </form>
    </div>
  );
}
