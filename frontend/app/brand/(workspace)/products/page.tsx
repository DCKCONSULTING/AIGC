"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import {
  api,
  endpoints,
  type Brand,
  type Category,
  type Product,
  type ProductShare,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

const PAGE_SIZE = 5;

const emptyProductForm = {
  brand: "",
  name: "",
  description: "",
  product_url: "",
  price: "",
  commission: "",
};

function ProductsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { token } = useAuth();
  const [brands, setBrands] = useState<Brand[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [dialog, setDialog] = useState<"add" | "edit" | null>(null);
  const [editing, setEditing] = useState<Product | null>(null);
  const [deleting, setDeleting] = useState<Product | null>(null);
  const [share, setShare] = useState<ProductShare | null>(null);
  const [gallery, setGallery] = useState<Product | null>(null);
  const [form, setForm] = useState(emptyProductForm);
  const [photos, setPhotos] = useState<File[]>([]);

  const brandFilter = searchParams.get("brand") ?? "";
  const categoryFilter = searchParams.get("category") ?? "";

  const companyName = useMemo(() => {
    if (brands.length === 0) return "Products";
    return [...brands].sort(
      (a, b) =>
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    )[0].name;
  }, [brands]);

  const pageCount = Math.max(1, Math.ceil(products.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const visible = products.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  );

  function setFilters(nextBrand: string, nextCategory: string) {
    const params = new URLSearchParams();
    if (nextBrand) params.set("brand", nextBrand);
    if (nextCategory) params.set("category", nextCategory);
    const query = params.toString();
    router.replace(query ? `/brand/products?${query}` : "/brand/products");
    setPage(1);
  }

  function load() {
    if (!token) return;
    Promise.all([
      api<Brand[]>(endpoints.brands.list, { token }),
      api<Category[]>(endpoints.brands.categories, { token }),
      api<Product[]>(
        endpoints.brands.productsQuery({
          brand: brandFilter || undefined,
          category: categoryFilter || undefined,
        }),
        { token },
      ),
    ]).then(([nextBrands, nextCategories, nextProducts]) => {
      setBrands(nextBrands);
      setCategories(nextCategories);
      setProducts(nextProducts);
      setError("");
      setPage((current) => {
        const nextCount = Math.max(1, Math.ceil(nextProducts.length / PAGE_SIZE));
        return Math.min(current, nextCount);
      });
    }).catch((err) => {
      setError(err instanceof Error ? err.message : "Unable to load products.");
    });
  }

  useEffect(() => {
    load();
  }, [token, brandFilter, categoryFilter]);

  function openAdd() {
    setError("");
    setEditing(null);
    setForm({
      ...emptyProductForm,
      brand: brandFilter || String(brands[0]?.id || ""),
    });
    setPhotos([]);
    setDialog("add");
  }

  function openEdit(product: Product) {
    setError("");
    setEditing(product);
    setForm({
      brand: String(product.brand),
      name: product.name,
      description: product.description,
      product_url: product.product_url,
      price: product.price,
      commission: product.commission,
    });
    setPhotos([]);
    setDialog("edit");
  }

  function closeDialog() {
    if (pending) return;
    setDialog(null);
    setEditing(null);
    setPhotos([]);
    setError("");
  }

  function buildPayload() {
    const payload = new FormData();
    payload.append("brand", form.brand);
    payload.append("name", form.name);
    payload.append("description", form.description);
    payload.append("product_url", form.product_url);
    payload.append("price", form.price);
    payload.append("commission", form.commission);
    photos.forEach((photo) => payload.append("photos", photo));
    return payload;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      if (dialog === "edit" && editing) {
        await api<Product>(endpoints.brands.productDetail(editing.id), {
          method: "PATCH",
          token,
          body: buildPayload(),
        });
      } else {
        await api<Product>(endpoints.brands.products, {
          method: "POST",
          token,
          body: buildPayload(),
        });
      }
      setDialog(null);
      setEditing(null);
      setForm(emptyProductForm);
      setPhotos([]);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save product.");
    } finally {
      setPending(false);
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    setPending(true);
    try {
      await api(endpoints.brands.productDetail(deleting.id), {
        method: "DELETE",
        token,
      });
      setDeleting(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete product.");
    } finally {
      setPending(false);
    }
  }

  async function onShare(product: Product) {
    setError("");
    try {
      const result = await api<ProductShare>(
        endpoints.brands.productShare(product.id),
        { method: "POST", token },
      );
      const url = `${window.location.origin}/s/${result.code}`;
      setShare({ ...result, url });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create share link.");
    }
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-gold">Products</p>
          <h1 className="mt-3 font-serif text-4xl">{companyName}</h1>
          <p className="mt-3 text-muted">
            All products for this company. Filter by brand or category, then
            edit, delete, or share a tracking link.
          </p>
        </div>
        <button
          type="button"
          onClick={openAdd}
          className="h-11 shrink-0 rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep"
        >
          Add product
        </button>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          Filter by brand
          <select
            value={brandFilter}
            onChange={(event) => setFilters(event.target.value, categoryFilter)}
            className="mt-2 h-11 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
          >
            <option value="">All brands</option>
            {brands.map((brand) => (
              <option key={brand.id} value={brand.id}>
                {brand.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          Filter by category
          <select
            value={categoryFilter}
            onChange={(event) => setFilters(brandFilter, event.target.value)}
            className="mt-2 h-11 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
          >
            <option value="">All categories</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-8 overflow-hidden rounded-2xl border border-line bg-card">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-line bg-background/70 text-xs uppercase tracking-[0.12em] text-muted">
              <tr>
                <th className="px-5 py-3 font-medium">Photos</th>
                <th className="px-5 py-3 font-medium">Product</th>
                <th className="px-5 py-3 font-medium">Brand</th>
                <th className="px-5 py-3 font-medium">Category</th>
                <th className="px-5 py-3 font-medium">Price</th>
                <th className="px-5 py-3 font-medium">Commission</th>
                <th className="px-5 py-3 font-medium">Shares / Opens</th>
                <th className="px-5 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((product) => (
                <tr key={product.id} className="border-b border-line last:border-0">
                  <td className="px-5 py-4">
                    {product.images[0] ? (
                      <button
                        type="button"
                        onClick={() => setGallery(product)}
                        className="relative block"
                        aria-label={`View photos for ${product.name}`}
                      >
                        <img
                          src={product.images[0].url}
                          alt=""
                          className="h-12 w-12 rounded-md object-cover"
                        />
                        {product.images.length > 1 ? (
                          <span className="absolute -right-1 -bottom-1 rounded-full bg-foreground px-1.5 text-[10px] leading-4 text-background">
                            {product.images.length}
                          </span>
                        ) : null}
                      </button>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="px-5 py-4">
                    <p className="font-medium">{product.name}</p>
                    <p className="line-clamp-2 text-xs text-muted">
                      {product.description}
                    </p>
                  </td>
                  <td className="px-5 py-4">{product.brand_name}</td>
                  <td className="px-5 py-4">{product.category_name || "—"}</td>
                  <td className="px-5 py-4">{product.price}</td>
                  <td className="px-5 py-4">{product.commission}%</td>
                  <td className="px-5 py-4">
                    {product.share_count} / {product.open_count}
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex flex-wrap justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => openEdit(product)}
                        className="rounded-full border border-line px-3 py-1.5 text-xs hover:bg-black/5"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => onShare(product)}
                        className="rounded-full border border-line px-3 py-1.5 text-xs hover:bg-black/5"
                      >
                        Share
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleting(product)}
                        className="rounded-full border border-red-200 px-3 py-1.5 text-xs text-red-700 hover:bg-red-50"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {visible.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center text-muted">
                    {error
                      ? error
                      : brandFilter
                        ? "No products for this brand."
                        : "No products yet. Use Add product to create the first one."}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3 text-sm">
          <p className="text-muted">
            {products.length === 0
              ? "0 products"
              : `${(currentPage - 1) * PAGE_SIZE + 1}–${Math.min(currentPage * PAGE_SIZE, products.length)} of ${products.length}`}
          </p>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => setPage((value) => value - 1)}
              className="rounded-lg border border-line px-3 py-1.5 disabled:opacity-40"
            >
              Prev
            </button>
            {Array.from({ length: pageCount }, (_, index) => index + 1).map(
              (number) => (
                <button
                  key={number}
                  type="button"
                  onClick={() => setPage(number)}
                  className={`min-w-9 rounded-lg px-3 py-1.5 ${
                    number === currentPage
                      ? "bg-gold"
                      : "border border-line hover:bg-black/5"
                  }`}
                >
                  {number}
                </button>
              ),
            )}
            <button
              type="button"
              disabled={currentPage >= pageCount}
              onClick={() => setPage((value) => value + 1)}
              className="rounded-lg border border-line px-3 py-1.5 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      {dialog ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/30"
            aria-label="Close"
            onClick={closeDialog}
          />
          <form
            onSubmit={onSubmit}
            className="relative max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-line bg-card p-6 shadow-lg"
          >
            <h2 className="font-serif text-2xl">
              {dialog === "edit" ? "Edit product" : "Add product"}
            </h2>
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
                  onChange={(event) =>
                    setForm({ ...form, brand: event.target.value })
                  }
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
                  onChange={(event) =>
                    setPhotos(Array.from(event.target.files ?? []))
                  }
                  className="mt-2 w-full text-sm"
                />
              </label>
              <label className="block text-sm">
                Product name
                <input
                  required
                  value={form.name}
                  onChange={(event) =>
                    setForm({ ...form, name: event.target.value })
                  }
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                Description
                <textarea
                  required
                  rows={3}
                  value={form.description}
                  onChange={(event) =>
                    setForm({ ...form, description: event.target.value })
                  }
                  className="mt-2 w-full rounded-xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                Product URL
                <input
                  required
                  type="url"
                  value={form.product_url}
                  onChange={(event) =>
                    setForm({ ...form, product_url: event.target.value })
                  }
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm">
                  Product price
                  <input
                    required
                    type="number"
                    min="0"
                    step="0.01"
                    value={form.price}
                    onChange={(event) =>
                      setForm({ ...form, price: event.target.value })
                    }
                    className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                  />
                </label>
                <label className="block text-sm">
                  Commission on sales (%)
                  <input
                    required
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={form.commission}
                    onChange={(event) =>
                      setForm({ ...form, commission: event.target.value })
                    }
                    className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                  />
                </label>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={closeDialog}
                className="h-11 rounded-full border border-line px-5 text-sm hover:bg-black/5"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={pending}
                className="h-11 rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep disabled:opacity-60"
              >
                {pending ? "Saving…" : dialog === "edit" ? "Save changes" : "Add product"}
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {deleting ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/30"
            aria-label="Close"
            onClick={() => !pending && setDeleting(null)}
          />
          <div className="relative w-full max-w-md rounded-2xl border border-line bg-card p-6 shadow-lg">
            <h2 className="font-serif text-2xl">Delete product</h2>
            <p className="mt-3 text-sm text-muted">
              Delete{" "}
              <span className="font-medium text-foreground">{deleting.name}</span>?
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setDeleting(null)}
                className="h-11 rounded-full border border-line px-5 text-sm hover:bg-black/5"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                disabled={pending}
                className="h-11 rounded-full bg-red-600 px-5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
              >
                {pending ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {gallery ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/30"
            aria-label="Close"
            onClick={() => setGallery(null)}
          />
          <div className="relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-line bg-card p-6 shadow-lg">
            <h2 className="font-serif text-2xl">{gallery.name}</h2>
            <p className="mt-1 text-sm text-muted">
              {gallery.images.length} photo{gallery.images.length === 1 ? "" : "s"}
            </p>
            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {gallery.images.map((image) => (
                <img
                  key={image.id}
                  src={image.url}
                  alt=""
                  className="h-40 w-full rounded-xl object-cover"
                />
              ))}
            </div>
            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={() => setGallery(null)}
                className="h-11 rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {share ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/30"
            aria-label="Close"
            onClick={() => setShare(null)}
          />
          <div className="relative w-full max-w-lg rounded-2xl border border-line bg-card p-6 shadow-lg">
            <h2 className="font-serif text-2xl">Share tracking link</h2>
            <p className="mt-2 text-sm text-muted">
              Anyone who opens this link is counted, then sent to the product URL.
            </p>
            <input
              readOnly
              value={share.url}
              className="mt-4 h-11 w-full rounded-xl border border-line bg-background px-4 text-sm"
            />
            <p className="mt-3 text-sm text-muted">
              Shared {share.share_count} times · Opened {share.open_count} times
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => navigator.clipboard.writeText(share.url)}
                className="h-11 rounded-full border border-line px-5 text-sm hover:bg-black/5"
              >
                Copy link
              </button>
              <button
                type="button"
                onClick={() => setShare(null)}
                className="h-11 rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function ProductsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-full items-center justify-center text-muted">
          Loading…
        </div>
      }
    >
      <ProductsContent />
    </Suspense>
  );
}
