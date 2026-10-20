"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { api, endpoints, type Brand, type Category, type Product } from "@/lib/api";
import { BRAND_CREATED_NOTICE, mergeCreatedBrand } from "@/lib/brand";
import { useAuth } from "@/lib/auth";

const PAGE_SIZE = 5;

const emptyForm = {
  category: "",
  name: "",
  website: "",
  location: "",
  description: "",
};

const emptyProductForm = {
  name: "",
  description: "",
  product_url: "",
  price: "",
  commission: "",
};

export default function BrandsPage() {
  const { token } = useAuth();
  const [brands, setBrands] = useState<Brand[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [dialog, setDialog] = useState<"add" | "edit" | null>(null);
  const [editing, setEditing] = useState<Brand | null>(null);
  const [deleting, setDeleting] = useState<Brand | null>(null);
  const [productBrand, setProductBrand] = useState<Brand | null>(null);
  const [productForm, setProductForm] = useState(emptyProductForm);
  const [productPhotos, setProductPhotos] = useState<File[]>([]);

  const companyName = useMemo(() => {
    if (brands.length === 0) return "Company";
    return [...brands].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    )[0].name;
  }, [brands]);

  const pageCount = Math.max(1, Math.ceil(brands.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const visible = brands.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  );

  function load() {
    if (!token) return;
    Promise.all([
      api<Brand[]>(endpoints.brands.list, { token }),
      api<Category[]>(endpoints.brands.categories, { token }),
    ]).then(([rows, nextCategories]) => {
      setBrands(rows);
      setCategories(nextCategories);
      setPage((current) => {
        const nextCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
        return Math.min(current, nextCount);
      });
    });
  }

  useEffect(() => {
    load();
  }, [token]);

  function openAdd() {
    setError("");
    setForm(emptyForm);
    setEditing(null);
    setDialog("add");
  }

  function openEdit(brand: Brand) {
    setError("");
    setEditing(brand);
    setForm({
      category: String(brand.category),
      name: brand.name,
      website: brand.website,
      location: brand.location,
      description: brand.description,
    });
    setDialog("edit");
  }

  function closeDialog() {
    if (pending) return;
    setDialog(null);
    setEditing(null);
    setError("");
  }

  function openAddProduct(brand: Brand) {
    setError("");
    setProductBrand(brand);
    setProductForm(emptyProductForm);
    setProductPhotos([]);
  }

  function closeProductDialog() {
    if (pending) return;
    setProductBrand(null);
    setProductForm(emptyProductForm);
    setProductPhotos([]);
    setError("");
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      const payload = {
        ...form,
        category: Number(form.category),
      };
      if (dialog === "edit" && editing) {
        const saved = await api<Brand>(endpoints.brands.detail(editing.id), {
          method: "PATCH",
          token,
          body: JSON.stringify(payload),
        });
        setBrands((current) => current.map((item) => (item.id === saved.id ? saved : item)));
        setNotice("Brand updated.");
      } else {
        const saved = await api<Brand>(endpoints.brands.list, {
          method: "POST",
          token,
          body: JSON.stringify(payload),
        });
        if (process.env.NODE_ENV === "development") {
          console.info("[brand] created", saved);
        }
        setBrands((current) => mergeCreatedBrand(current, saved));
        setNotice(BRAND_CREATED_NOTICE);
      }
      setDialog(null);
      setEditing(null);
      setForm(emptyForm);
      load();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to save brand.";
      if (process.env.NODE_ENV === "development") {
        console.error("[brand] save failed", message);
      }
      setError(message);
      setNotice("");
    } finally {
      setPending(false);
    }
  }

  async function onCreateProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!productBrand) return;
    setError("");
    setPending(true);
    try {
      const payload = new FormData();
      payload.append("brand", String(productBrand.id));
      payload.append("name", productForm.name);
      payload.append("description", productForm.description);
      payload.append("product_url", productForm.product_url);
      payload.append("price", productForm.price);
      payload.append("commission", productForm.commission);
      productPhotos.forEach((photo) => payload.append("photos", photo));
      await api<Product>(endpoints.brands.products, {
        method: "POST",
        token,
        body: payload,
      });
      setProductBrand(null);
      setProductForm(emptyProductForm);
      setProductPhotos([]);
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
      await api(endpoints.brands.detail(deleting.id), {
        method: "DELETE",
        token,
      });
      setDeleting(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete brand.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-gold">Brands</p>
          <h1 className="mt-3 font-serif text-4xl">{companyName}</h1>
          <p className="mt-3 text-muted">
            All brands under this company. Add a brand, then edit or delete it
            from the table.
          </p>
        </div>
        <button
          type="button"
          onClick={openAdd}
          className="h-11 shrink-0 rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep"
        >
          Add brand
        </button>
      </div>
      {notice ? (
        <p className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm" role="status">
          {notice}
        </p>
      ) : null}

      <div className="mt-8 overflow-hidden rounded-2xl border border-line bg-card">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-line bg-background/70 text-xs uppercase tracking-[0.12em] text-muted">
              <tr>
                <th className="px-5 py-3 font-medium">Brand</th>
                <th className="px-5 py-3 font-medium">Category</th>
                <th className="px-5 py-3 font-medium">Website</th>
                <th className="px-5 py-3 font-medium">Location</th>
                <th className="px-5 py-3 font-medium">Description</th>
                <th className="px-5 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((brand) => (
                <tr key={brand.id} className="border-b border-line last:border-0">
                  <td className="px-5 py-4 font-medium">{brand.name}</td>
                  <td className="px-5 py-4">{brand.category_name || "—"}</td>
                  <td className="px-5 py-4">
                    {brand.website ? (
                      <a
                        href={brand.website}
                        className="text-gold hover:underline"
                        target="_blank"
                        rel="noreferrer"
                      >
                        {brand.website.replace(/^https?:\/\//, "")}
                      </a>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="px-5 py-4">{brand.location || "—"}</td>
                  <td className="max-w-xs px-5 py-4 text-muted">
                    <p className="line-clamp-2">{brand.description || "—"}</p>
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex flex-wrap justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => openAddProduct(brand)}
                        className="rounded-full border border-line px-3 py-1.5 text-xs hover:bg-black/5"
                      >
                        Add product
                      </button>
                      <Link
                        href={`/brand/products?brand=${brand.id}`}
                        className="rounded-full border border-line px-3 py-1.5 text-xs hover:bg-black/5"
                      >
                        Product list
                      </Link>
                      <button
                        type="button"
                        onClick={() => openEdit(brand)}
                        className="rounded-full border border-line px-3 py-1.5 text-xs hover:bg-black/5"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleting(brand)}
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
                  <td colSpan={6} className="px-5 py-12 text-center text-muted">
                    No brands yet. Use Add brand to create the first one.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3 text-sm">
          <p className="text-muted">
            {brands.length === 0
              ? "0 brands"
              : `${(currentPage - 1) * PAGE_SIZE + 1}–${Math.min(currentPage * PAGE_SIZE, brands.length)} of ${brands.length}`}
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
            className="relative w-full max-w-lg rounded-2xl border border-line bg-card p-6 shadow-lg"
          >
            <h2 className="font-serif text-2xl">
              {dialog === "edit" ? "Edit brand" : "Add brand"}
            </h2>
            {error ? (
              <p className="mt-4 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </p>
            ) : null}
            <div className="mt-5 grid gap-4">
              <label className="block text-sm">
                Category
                <select
                  required
                  value={form.category}
                  onChange={(event) =>
                    setForm({ ...form, category: event.target.value })
                  }
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                >
                  <option value="" disabled>
                    Select a category
                  </option>
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                Brand name
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
                Website
                <input
                  value={form.website}
                  onChange={(event) =>
                    setForm({ ...form, website: event.target.value })
                  }
                  placeholder="https://yourbrand.com"
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                Location
                <input
                  value={form.location}
                  onChange={(event) =>
                    setForm({ ...form, location: event.target.value })
                  }
                  placeholder="City, country"
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                Description
                <textarea
                  rows={3}
                  value={form.description}
                  onChange={(event) =>
                    setForm({ ...form, description: event.target.value })
                  }
                  className="mt-2 w-full rounded-xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
                />
              </label>
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
                {pending ? "Saving…" : dialog === "edit" ? "Save changes" : "Add brand"}
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
            <h2 className="font-serif text-2xl">Delete brand</h2>
            <p className="mt-3 text-sm text-muted">
              Delete <span className="font-medium text-foreground">{deleting.name}</span>?
              Products under this brand will be removed too.
            </p>
            {error ? (
              <p className="mt-4 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </p>
            ) : null}
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setDeleting(null)}
                disabled={pending}
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

      {productBrand ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/30"
            aria-label="Close"
            onClick={closeProductDialog}
          />
          <form
            onSubmit={onCreateProduct}
            className="relative max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-line bg-card p-6 shadow-lg"
          >
            <h2 className="font-serif text-2xl">Add product</h2>
            <p className="mt-1 text-sm text-muted">{productBrand.name}</p>
            {error ? (
              <p className="mt-4 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </p>
            ) : null}
            <div className="mt-5 grid gap-4">
              <label className="block text-sm">
                Photos
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  onChange={(event) =>
                    setProductPhotos(Array.from(event.target.files ?? []))
                  }
                  className="mt-2 w-full text-sm"
                />
              </label>
              {productPhotos.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {productPhotos.map((photo) => (
                    <span
                      key={`${photo.name}-${photo.size}`}
                      className="rounded-full bg-background px-3 py-1 text-xs text-muted"
                    >
                      {photo.name}
                    </span>
                  ))}
                </div>
              ) : null}
              <label className="block text-sm">
                Product name
                <input
                  required
                  value={productForm.name}
                  onChange={(event) =>
                    setProductForm({ ...productForm, name: event.target.value })
                  }
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                Description
                <textarea
                  required
                  rows={3}
                  value={productForm.description}
                  onChange={(event) =>
                    setProductForm({
                      ...productForm,
                      description: event.target.value,
                    })
                  }
                  className="mt-2 w-full rounded-xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                Product URL
                <input
                  required
                  type="url"
                  value={productForm.product_url}
                  onChange={(event) =>
                    setProductForm({
                      ...productForm,
                      product_url: event.target.value,
                    })
                  }
                  placeholder="https://shop.example.com/product"
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
                    value={productForm.price}
                    onChange={(event) =>
                      setProductForm({ ...productForm, price: event.target.value })
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
                    value={productForm.commission}
                    onChange={(event) =>
                      setProductForm({
                        ...productForm,
                        commission: event.target.value,
                      })
                    }
                    className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                  />
                </label>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={closeProductDialog}
                className="h-11 rounded-full border border-line px-5 text-sm hover:bg-black/5"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={pending}
                className="h-11 rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep disabled:opacity-60"
              >
                {pending ? "Saving…" : "Add product"}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
