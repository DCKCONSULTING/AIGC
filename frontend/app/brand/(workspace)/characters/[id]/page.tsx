"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { CharacterForm, draftFromCharacter } from "@/components/characters/CharacterForm";
import { api, endpoints, type Brand, type StudioCharacter, type VoiceOption } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function EditCharacterPage() {
  const { token } = useAuth();
  const params = useParams<{ id: string }>();
  const [character, setCharacter] = useState<StudioCharacter | null>(null);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token || !params.id) return;
    Promise.all([
      api<StudioCharacter>(endpoints.ai.characterDetail(Number(params.id)), { token }),
      api<Brand[]>(endpoints.brands.list, { token }),
      api<VoiceOption[]>(endpoints.ai.voices, { token }).catch(() => []),
    ])
      .then(([nextCharacter, nextBrands, nextVoices]) => {
        setCharacter(nextCharacter);
        setBrands(nextBrands);
        setVoices(nextVoices);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unable to open this character."));
  }, [token, params.id]);

  if (error) {
    return <p className="text-sm">{error}</p>;
  }
  if (!token || !character) {
    return <p className="text-sm text-muted">Loading…</p>;
  }

  return (
    <div>
      <Link href="/brand/characters" className="text-sm text-muted">
        Characters
      </Link>
      <h1 className="mt-3 font-serif text-4xl">{character.name}</h1>
      {note ? <p className="mt-3 text-sm">{note}</p> : null}
      <div className="mt-6">
        <CharacterForm
          token={token}
          brands={brands}
          voices={voices}
          characterId={character.id}
          existingPreview={character.preview_url}
          savedReferenceCount={character.references?.length || 0}
          initial={draftFromCharacter(character)}
          character={character}
          onSaved={(saved) => {
            setCharacter(saved);
            setNote("Character saved. Existing video snapshots stay as they were.");
          }}
        />
      </div>
    </div>
  );
}
