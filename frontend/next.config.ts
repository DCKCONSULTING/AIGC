import type { NextConfig } from "next";

const backend =
  process.env.DJANGO_API_ORIGIN ?? "http://127.0.0.1:8000";
const siteHost =
  process.env.NEXT_PUBLIC_SITE_URL
    ? new URL(process.env.NEXT_PUBLIC_SITE_URL).hostname
    : "brand.dckwebgen.com";

const nextConfig: NextConfig = {
  skipTrailingSlashRedirect: true,
  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",
    "172.19.192.1",
    siteHost,
  ],
  async rewrites() {
    return [
      {
        source: "/api/:path*/",
        destination: `${backend}/api/:path*/`,
      },
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*/`,
      },
      {
        source: "/media/:path*",
        destination: `${backend}/media/:path*`,
      },
      {
        source: "/s/:code",
        destination: `${backend}/s/:code/`,
      },
      {
        source: "/s/:code/",
        destination: `${backend}/s/:code/`,
      },
    ];
  },
};

export default nextConfig;
