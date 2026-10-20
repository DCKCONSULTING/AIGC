"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { CharacterForm, emptyCharacterDraft } from "@/components/characters/CharacterForm";
import { api, endpoints, type Brand, type StudioCharacter, type VoiceOption } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function NewCharacterPage() {
  const { token } = useAuth();
  const router = useRouter();
  const [brands, setBrands] = useState<Brand[]>([]);
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!token) return;
    Promise.all([
      api<Brand[]>(endpoints.brands.list, { token }),
      api<VoiceOption[]>(endpoints.ai.voices, { token }).catch(() => []),
    ]).then(([nextBrands, nextVoices]) => {
      setBrands(nextBrands);
      setVoices(nextVoices);
    });
  }, [token]);

  if (!token || !brands.length) {
    return <p className="text-sm text-muted">Loading…</p>;
  }

  return (
    <div>
      <Link href="/brand/characters" className="text-sm text-muted">
        Characters
      </Link>
      <h1 className="mt-3 font-serif text-4xl">Create character</h1>
      {note ? <p className="mt-3 text-sm">{note}</p> : null}
      <div className="mt-6">
        <CharacterForm
          token={token}
          brands={brands}
          voices={voices}
          initial={emptyCharacterDraft(String(brands[0].id))}
          submitLabel="Create character"
          onSaved={(character: StudioCharacter) => {
            setNote("Character created successfully.");
            router.push(`/brand/characters/${character.id}`);
          }}
        />
      </div>
    </div>
  );
}
