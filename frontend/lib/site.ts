const trimTrailingSlash = (value: string) => value.replace(/\/+$/, "");

/** Canonical public origin for metadata, share links, and production hosts. */
export const SITE_URL = trimTrailingSlash(
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://brand.dckwebgen.com",
);

export const SITE_HOST = new URL(SITE_URL).hostname;
