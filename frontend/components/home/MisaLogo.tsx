import Image from "next/image";

const variants = {
  wordmark: {
    src: "/misa/logo-wordmark.png",
    width: 771,
    height: 178,
  },
  "wordmark-on-dark": {
    src: "/misa/logo-wordmark-on-dark.png",
    width: 771,
    height: 178,
  },
  full: {
    src: "/misa/logo.png",
    width: 770,
    height: 236,
  },
  "full-on-dark": {
    src: "/misa/logo-on-dark.png",
    width: 770,
    height: 236,
  },
} as const;

export function MisaLogo({
  className = "h-9 w-auto",
  variant = "word",
  title = "MiSa",
  priority = false,
}: {
  className?: string;
  variant?: keyof typeof variants | "word" | "word-tag";
  title?: string;
  priority?: boolean;
}) {
  if (variant === "word" || variant === "word-tag") {
    return (
      <span className={`misa-logo ${className}`.trim()} aria-label={title}>
        <span className="misa-logo-word">MiSa</span>
        {variant === "word-tag" ? (
          <span className="misa-logo-tag">AI video generation platform</span>
        ) : null}
      </span>
    );
  }

  const asset = variants[variant];
  return (
    <Image
      src={asset.src}
      alt={title}
      width={asset.width}
      height={asset.height}
      className={className}
      priority={priority}
    />
  );
}
