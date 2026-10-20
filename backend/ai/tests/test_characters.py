import inspect
import io
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import User
from ai.models import (
    Character,
    CharacterStatus,
    LanguageChoice,
    Scene,
    StyleChoice,
    StyleRecipe,
    VideoAsset,
    VideoCharacterConfig,
    VideoProject,
    VideoProjectStatus,
)
from ai.providers.google.omni import GeminiOmniProvider
from ai.serializers import VideoCharacterConfigSerializer
from ai.services.characters import (
    VOICE_ROLE,
    character_from_presenter,
    materialize_character_references,
    sync_project_character,
)
from ai.services.compiler import compile_scene_prompt
from ai.services.script import LANGUAGE_GUIDE, STYLE_GUIDE, speech_lock
from ai.services.snapshots import product_snapshot
from ai.services.style_recipes import apply_recipe_to_project, bulk_create_from_recipe
from ai.services.video import VideoGenerationService
from brands.models import Brand, Category, Product, ProductImage


def _png(name="face.png") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 40, 80)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class CharacterApiTests(APITestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Studio", slug="studio-characters")
        self.owner = User.objects.create_user(
            username="char-owner",
            email="char-owner@example.com",
            password="password123",
            name="Owner",
            mobile="0123000001",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        self.other = User.objects.create_user(
            username="char-other",
            email="char-other@example.com",
            password="password123",
            name="Other",
            mobile="0123000002",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(owner=self.owner, category=self.category, name="MiSa Home")
        self.other_brand = Brand.objects.create(owner=self.other, category=self.category, name="Other Home")
        self.product = Product.objects.create(
            brand=self.brand,
            name="Serum",
            description="Daily face serum.",
            price="89.00",
        )
        ProductImage.objects.create(product=self.product, image=_png("product.png"))
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.owner).key}")

    def _create(self, **extra):
        payload = {
            "brand": self.brand.id,
            "name": "Sarah",
            "gender": "female",
            "appearance_description": "Shoulder-length black hair, light blue blazer.",
            "default_language": "english",
            "default_tone": "warm",
        }
        payload.update(extra)
        return self.client.post("/api/ai/characters/", payload, format="multipart")

    def test_crud_archive_restore_duplicate_and_isolation(self):
        created = self._create()
        self.assertEqual(created.status_code, 201, created.data)
        character_id = created.data["id"]
        self.assertTrue(created.data["default_voice_id"])
        self.assertEqual(created.data["default_voice_provider"], "google_tts")

        listed = self.client.get("/api/ai/characters/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data), 1)

        updated = self.client.patch(
            f"/api/ai/characters/{character_id}/",
            {"description": "Explains products calmly."},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["description"], "Explains products calmly.")

        cloned = self.client.post(f"/api/ai/characters/{character_id}/duplicate/", {"name": "Sarah — Premium"}, format="json")
        self.assertEqual(cloned.status_code, 201)
        self.assertNotEqual(cloned.data["id"], character_id)
        self.assertEqual(cloned.data["name"], "Sarah — Premium")

        archived = self.client.post(f"/api/ai/characters/{character_id}/archive/")
        self.assertEqual(archived.status_code, 200)
        visible = self.client.get("/api/ai/characters/")
        self.assertFalse(any(item["id"] == character_id for item in visible.data))
        with_archived = self.client.get("/api/ai/characters/?archived=1")
        self.assertTrue(any(item["id"] == character_id for item in with_archived.data))
        restored = self.client.post(f"/api/ai/characters/{character_id}/restore/")
        self.assertEqual(restored.data["status"], "active")

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.other).key}")
        hidden = self.client.get(f"/api/ai/characters/{character_id}/")
        self.assertEqual(hidden.status_code, 404)
        leaked = self.client.get("/api/ai/characters/")
        self.assertEqual(leaked.data, [])

    def test_rejects_missing_visual_and_bad_voice(self):
        missing = self.client.post(
            "/api/ai/characters/",
            {"brand": self.brand.id, "name": "No Face", "gender": "female", "appearance_description": ""},
            format="multipart",
        )
        self.assertEqual(missing.status_code, 400)
        bad_voice = self._create(default_voice_id="not-a-real-voice")
        self.assertEqual(bad_voice.status_code, 400)

    def test_video_override_does_not_mutate_character_and_snapshot_stays(self):
        created = self._create()
        character = Character.objects.get(pk=created.data["id"])
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            speaking_style="warm",
            speaker_gender="female",
            creative_brief={"schema_version": 2, "objective": "buy", "customer": "Shoppers", "main_benefit": "Glow"},
            status=VideoProjectStatus.DRAFT,
        )
        sync_project_character(
            project,
            character.pk,
            language="mandarin_my",
            tone="luxury",
            gender="male",
            voice_id="",
        )
        character.refresh_from_db()
        self.assertEqual(character.default_language, "english")
        self.assertEqual(character.default_tone, "warm")
        self.assertEqual(character.gender, "female")
        config = VideoCharacterConfig.objects.get(project=project)
        self.assertEqual(config.language, "mandarin_my")
        self.assertEqual(config.tone, "luxury")
        self.assertEqual(config.gender, "male")
        self.assertIn("cmn-CN", config.voice_id)
        appearance = config.appearance_snapshot
        character.appearance_description = "Completely different person."
        character.default_language = "hokkien"
        character.save()
        config.refresh_from_db()
        self.assertEqual(config.appearance_snapshot, appearance)
        self.assertEqual(config.language, "mandarin_my")
        self.assertEqual(self.product.name, "Serum")

    def test_generation_prompt_includes_character_without_replacing_product(self):
        created = self._create()
        character = Character.objects.get(pk=created.data["id"])
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            speaking_style="warm",
            speaker_gender="female",
            status=VideoProjectStatus.DRAFT,
            creative_brief={"must_remain_exact": ["product_appearance", "product_name", "price"]},
        )
        scene = Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            title="Hook",
            visual="Show the bottle",
            narration="Try this serum.",
            caption="Serum",
            metadata={"product_locked": True},
        )
        sync_project_character(project, character.pk, language="english", tone="warm", gender="female")
        scene.refresh_from_db()
        prompt = compile_scene_prompt(scene, project)
        self.assertIn(f"id {character.pk}", prompt)
        self.assertIn("Shoulder-length black hair", prompt)
        self.assertIn("Serum", prompt)
        self.assertIn("PRODUCT TRUTH", prompt)
        self.assertEqual(scene.metadata.get("character_id"), character.pk)

    def test_veo_prompt_keeps_master_reference_without_character_name(self):
        from ai.services.compiler import compile_film_prompt

        created = self._create(name="Huat Ge")
        character = Character.objects.get(pk=created.data["id"])
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            speaking_style="warm",
            speaker_gender="male",
            duration_seconds=45,
            status=VideoProjectStatus.DRAFT,
            creative_brief={"pipeline": "studio"},
        )
        sync_project_character(project, character.pk, language="english", tone="warm", gender="male")
        config = project.character_config
        identity = dict(config.identity_snapshot or {})
        identity["master_reference_image"] = "master.png"
        identity["name"] = "Huat Ge"
        identity["id"] = character.pk
        config.identity_snapshot = identity
        config.save(update_fields=["identity_snapshot"])
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="Huat Ge holding a steaming dish.",
            narration="Budget meal?",
            duration=7.5,
            metadata={"shot_description": "Huat Ge holding a steaming dish.", "presenter_action": "Huat Ge presents the dish."},
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-2",
            order=2,
            visual="Huat Ge showing the price.",
            narration="Only RM21.80.",
            duration=7.5,
            metadata={"presenter_action": "Points at the price."},
        )
        scenes = list(project.scenes.order_by("order"))
        prompt = compile_film_prompt(project, scenes, 0, 8, extend=False, provider="veo")
        self.assertNotIn("Huat Ge", prompt)
        self.assertNotIn(f"id {character.pk}", prompt)
        self.assertNotIn("Character identifier", prompt)
        self.assertIn("master character reference", prompt.lower())
        self.assertIn("Shoulder-length black hair", prompt)
        self.assertIn("[0-7.5s]", prompt)
        self.assertIn("[7.5-8s]", prompt)
        self.assertNotIn("[8-8s]", prompt)
        self.assertIn("the presenter holding a steaming dish", prompt)
        scene = project.scenes.get(scene_key="scene-1")
        self.assertIn("Huat Ge", scene.visual)

    def test_style_apply_keeps_character_identity(self):
        created = self._create()
        character = Character.objects.get(pk=created.data["id"])
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            speaking_style="bold",
            speaker_gender="male",
            selected_concept_id="demo",
            creative_brief={"character_id": character.pk, "presenter": {"look": "other person"}},
            status=VideoProjectStatus.DRAFT,
        )
        apply_recipe_to_project(
            project,
            {
                "language": "english",
                "speaking_style": "bold",
                "speaker_gender": "male",
                "presenter": {"look": "style presenter", "ethnicity": "european"},
                "scene_blueprint": [],
                "objective": "buy",
                "main_benefit": "Glow",
            },
            overrides={"character_id": character.pk},
        )
        project.refresh_from_db()
        config = project.character_config
        self.assertEqual(config.identity_snapshot["id"], character.pk)
        self.assertIn("Shoulder-length black hair", config.appearance_snapshot)
        self.assertEqual(project.product.name, "Serum")

    def test_delete_is_blocked_when_a_video_uses_the_character(self):
        created = self._create()
        character = Character.objects.get(pk=created.data["id"])
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY_FOR_REVIEW,
        )
        sync_project_character(project, character.pk, language="english", tone="warm", gender="female")
        denied = self.client.delete(f"/api/ai/characters/{character.pk}/")
        self.assertEqual(denied.status_code, 409)
        self.assertTrue(Character.objects.filter(pk=character.pk).exists())
        self.assertTrue(VideoProject.objects.filter(pk=project.pk).exists())

    def _bound_project(self, character, **project_fields):
        payload = dict(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            speaking_style="warm",
            speaker_gender="female",
            status=VideoProjectStatus.DRAFT,
            creative_brief={"must_remain_exact": ["product_appearance", "product_name", "price"]},
        )
        payload.update(project_fields)
        project = VideoProject.objects.create(**payload)
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="Show the bottle",
            narration="Try this.",
            caption="Serum",
            metadata={"product_locked": True},
        )
        sync_project_character(
            project,
            character.pk,
            language=project.language,
            tone=project.speaking_style,
            gender=project.speaker_gender,
        )
        project.refresh_from_db()
        return project

    def test_voice_preference_is_not_verified_audio(self):
        created = self._create(default_voice_id="en-US-Wavenet-F")
        character = Character.objects.get(pk=created.data["id"])
        project = self._bound_project(character)
        config = project.character_config
        self.assertEqual(config.voice_id, "en-US-Wavenet-F")
        self.assertEqual(config.voice_provider, "google_tts")
        payload = VideoCharacterConfigSerializer(config).data
        self.assertEqual(payload["voice_role"], VOICE_ROLE)
        self.assertEqual(payload["voice_role"], "preference")
        self.assertNotIn("voice_id", inspect.signature(GeminiOmniProvider.start).parameters)
        prompt = compile_scene_prompt(project.scenes.get(), project)
        self.assertIn("Preferred speaking voice: en-US-Wavenet-F", prompt)
        self.assertNotIn("synthesized by", prompt.lower())
        self.assertNotIn("voice verified", prompt.lower())
        self.assertFalse(getattr(project, "narration_audio", None))

    def test_languages_and_tones_reach_the_scene_prompt(self):
        created = self._create()
        character = Character.objects.get(pk=created.data["id"])
        for language in LanguageChoice.values:
            project = self._bound_project(character, language=language, speaking_style="warm")
            prompt = compile_scene_prompt(project.scenes.get(), project)
            self.assertIn(LANGUAGE_GUIDE[language], prompt)
            self.assertTrue(prompt.startswith("SPOKEN AUDIO — LOCKED LANGUAGE"))
            self.assertIn(f"Spoken language id: {language}", prompt)
            if language in {"chinese", "cantonese", "hokkien", "mandarin_my"}:
                self.assertIn(speech_lock(language), prompt)
            if language != "english":
                self.assertNotIn(LANGUAGE_GUIDE["english"], prompt)
            if language == "hokkien":
                self.assertIn("native Hokkien speaker", prompt)
                self.assertNotIn("Preferred speaking voice: cmn-TW", prompt)
            if language == "cantonese":
                self.assertIn("CANTONESE ONLY", prompt)
                self.assertIn("yue-HK", prompt)
        tone_labels = {"warm": "Friendly", "calm": "Casual", "bold": "Energetic", "luxury": "Premium"}
        self.assertEqual(set(tone_labels.values()), {"Friendly", "Casual", "Energetic", "Premium"})
        for tone in StyleChoice.values:
            project = self._bound_project(character, language="english", speaking_style=tone)
            prompt = compile_scene_prompt(project.scenes.get(), project)
            self.assertIn(STYLE_GUIDE[tone], prompt)
            self.assertIn(f"tone {tone}", prompt)

    def test_voice_gender_override_does_not_replace_the_face(self):
        created = self.client.post(
            "/api/ai/characters/",
            {
                "brand": self.brand.id,
                "name": "Sarah",
                "gender": "female",
                "appearance_description": "Shoulder-length black hair, light blue blazer.",
                "default_language": "english",
                "reference_front": _png("sarah.png"),
            },
            format="multipart",
        )
        self.assertEqual(created.status_code, 201, created.data)
        character = Character.objects.get(pk=created.data["id"])
        original_id = character.pk
        original_files = list(character.references.values_list("image", flat=True))
        project = self._bound_project(character, speaker_gender="male")
        character.refresh_from_db()
        self.assertEqual(character.pk, original_id)
        self.assertEqual(character.gender, "female")
        self.assertEqual(list(character.references.values_list("image", flat=True)), original_files)
        self.assertEqual(project.character_config.gender, "male")
        self.assertEqual(project.character_config.identity_snapshot["id"], original_id)
        self.assertIn("light blue blazer", project.character_config.appearance_snapshot)

    def test_deleting_a_video_does_not_remove_the_character_photo(self):
        from pathlib import Path

        from ai.views import _delete_project_media

        created = self.client.post(
            "/api/ai/characters/",
            {
                "brand": self.brand.id,
                "name": "Sarah",
                "gender": "female",
                "appearance_description": "Light blue blazer.",
                "reference_front": _png("face.png"),
            },
            format="multipart",
        )
        self.assertEqual(created.status_code, 201, created.data)
        character = Character.objects.get(pk=created.data["id"])
        photo = character.references.get()
        photo_path = Path(photo.image.path)
        source_path = Path(character.source_front_image.path)
        self.assertTrue(photo_path.exists())
        self.assertTrue(source_path.exists())
        project = self._bound_project(character)
        asset = project.assets.get(metadata__character_reference=True)
        self.assertNotEqual(asset.file.name, photo.image.name)
        self.assertTrue(Path(asset.file.path).exists())
        asset.file.name = photo.image.name
        asset.save(update_fields=["file"])
        _delete_project_media(project)
        self.assertTrue(photo_path.exists())
        self.assertTrue(source_path.exists())
        detail = self.client.get(f"/api/ai/characters/{character.pk}/")
        self.assertTrue(detail.data["preview_url"])
        photo_path.unlink()
        source_path.unlink()
        missing = self.client.get(f"/api/ai/characters/{character.pk}/")
        self.assertEqual(missing.data["preview_url"], "")
        self.assertEqual(missing.data["source_front_url"], "")
        self.assertEqual(missing.data["references"][0]["url"], "")

    def test_product_photo_stays_ahead_of_character_references(self):
        created = self.client.post(
            "/api/ai/characters/",
            {
                "brand": self.brand.id,
                "name": "Sarah",
                "gender": "female",
                "appearance_description": "Light blue blazer.",
                "reference_front": _png("face.png"),
            },
            format="multipart",
        )
        character = Character.objects.get(pk=created.data["id"])
        project = self._bound_project(character)
        service = VideoGenerationService(
            product_service=MagicMock(),
            reference_service=MagicMock(),
            script_service=MagicMock(),
            images=MagicMock(),
            omni=MagicMock(),
            speech=MagicMock(),
            qa=MagicMock(),
        )
        refs = service._reference_images(project)
        product_path = self.product.images.first().image.path
        self.assertTrue(refs)
        self.assertEqual(refs[0], product_path)
        self.assertTrue(any("face" in path or path != product_path for path in refs[1:]))
        prompt = compile_scene_prompt(project.scenes.get(), project)
        self.assertIn("PRODUCT TRUTH", prompt)
        self.assertIn("Serum", prompt)
        self.assertIn("product locks stay authoritative", prompt.lower())

    def test_archived_character_keeps_the_frozen_snapshot(self):
        created = self._create()
        character = Character.objects.get(pk=created.data["id"])
        project = self._bound_project(character, status=VideoProjectStatus.READY_FOR_REVIEW)
        frozen = project.character_config.appearance_snapshot
        character.status = CharacterStatus.ARCHIVED
        character.appearance_description = "A different person."
        character.default_voice_id = "en-US-Wavenet-D"
        character.save()
        materialize_character_references(project)
        project.character_config.refresh_from_db()
        self.assertEqual(project.character_config.appearance_snapshot, frozen)
        prompt = compile_scene_prompt(project.scenes.get(), project)
        self.assertIn(frozen, prompt)
        self.assertNotIn("A different person.", prompt)
        with self.assertRaises(Exception):
            sync_project_character(project, character.pk, language="english", tone="warm", gender="female")
        hidden = self.client.get("/api/ai/characters/")
        self.assertFalse(any(item["id"] == character.pk for item in hidden.data))

    def test_delete_unused_character_and_keep_archived_references(self):
        unused = self._create(name="Unused")
        removed = self.client.delete(f"/api/ai/characters/{unused.data['id']}/")
        self.assertEqual(removed.status_code, 204)
        created = self._create()
        character = Character.objects.get(pk=created.data["id"])
        project = self._bound_project(character, status=VideoProjectStatus.EXPORTED)
        self.client.post(f"/api/ai/characters/{character.pk}/archive/")
        denied = self.client.delete(f"/api/ai/characters/{character.pk}/")
        self.assertEqual(denied.status_code, 409)
        self.assertTrue(VideoProject.objects.filter(pk=project.pk).exists())
        self.assertTrue(VideoCharacterConfig.objects.filter(project=project, character=character).exists())

    def test_brand_isolation_blocks_idor(self):
        created = self._create()
        character_id = created.data["id"]
        other_token = Token.objects.create(user=self.other)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {other_token.key}")
        for method, path, body in (
            ("get", f"/api/ai/characters/{character_id}/", None),
            ("patch", f"/api/ai/characters/{character_id}/", {"name": "Stolen"}),
            ("post", f"/api/ai/characters/{character_id}/duplicate/", {"name": "Stolen"}),
            ("post", f"/api/ai/characters/{character_id}/archive/", {}),
        ):
            response = getattr(self.client, method)(path, body, format="json")
            self.assertEqual(response.status_code, 404, response.data)
        self.assertEqual(Character.objects.get(pk=character_id).name, "Sarah")

    def test_api_rejects_invalid_character_state(self):
        self.assertEqual(self._create(gender="unknown").status_code, 400)
        self.assertEqual(self._create(default_language="klingon").status_code, 400)
        self.assertEqual(self._create(default_tone="shouty").status_code, 400)
        self.assertEqual(self._create(name="").status_code, 400)
        bad_image = SimpleUploadedFile("bad.png", b"not-an-image", content_type="image/png")
        self.assertEqual(
            self._create(reference_front=bad_image, appearance_description="").status_code,
            400,
        )
        self.assertEqual(self.client.get("/api/ai/characters/99999/").status_code, 404)
        created = self._create()
        self.client.post(f"/api/ai/characters/{created.data['id']}/archive/")
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            speaking_style="warm",
            speaker_gender="female",
            status=VideoProjectStatus.DRAFT,
        )
        with self.assertRaises(Exception):
            sync_project_character(project, created.data["id"], language="english", tone="warm", gender="female")
        other_brand = Brand.objects.create(owner=self.owner, category=self.category, name="Second brand")
        foreign = Character.objects.create(
            owner=self.owner,
            brand=other_brand,
            name="Elsewhere",
            gender="female",
            appearance_description="Other brand look.",
            default_language="english",
            default_tone="warm",
        )
        with self.assertRaises(Exception):
            sync_project_character(project, foreign.pk, language="english", tone="warm", gender="female")

    def test_save_as_character_reuses_presenter_file(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            speaking_style="luxury",
            speaker_gender="female",
            creative_brief={"presenter": {"look": "Light blue blazer.", "gender": "female"}},
            status=VideoProjectStatus.DRAFT,
        )
        asset = VideoAsset(project=project, kind=VideoAsset.Kind.IMAGE, prompt="presenter-reference")
        asset.file.save("presenter.png", _png("presenter.png"), save=True)
        asset.metadata = {"presenter_reference": True, "presenter_photo": True, "angle": "front"}
        asset.save(update_fields=["metadata"])
        character = character_from_presenter(project, {"name": "Sarah"})
        self.assertIsInstance(character, Character)
        self.assertEqual(character.references.get().image.name, asset.file.name)
        self.assertTrue(VideoAsset.objects.filter(pk=asset.pk).exists())
        self.assertEqual(character.default_tone, "luxury")

    def test_bulk_reuses_one_character(self):
        created = self._create()
        character = Character.objects.get(pk=created.data["id"])
        second = Product.objects.create(brand=self.brand, name="Toner", description="Toner.", price="49.00")
        third = Product.objects.create(brand=self.brand, name="Cream", description="Cream.", price="59.00")
        master = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            status=VideoProjectStatus.READY_FOR_REVIEW,
            qa_status="passed",
        )
        recipe = StyleRecipe.objects.create(
            owner=self.owner,
            key="kitchen",
            name="Kitchen",
            source_project=master,
            recipe={
                "language": "english",
                "speaking_style": "luxury",
                "speaker_gender": "female",
                "scene_blueprint": [{"shot_shape": "Show the product for the product.", "duration": 5}],
                "duration_seconds": 45,
                "objective": "buy",
                "main_benefit": "Glow",
            },
        )
        with patch("ai.services.style_recipes.enqueue_video_generation"):
            created_projects = bulk_create_from_recipe(
                owner=self.owner,
                recipe=recipe,
                products=[self.product, second, third],
                overrides={"character_id": character.pk},
            )
        self.assertEqual(len(created_projects), 3)
        self.assertEqual(Character.objects.filter(owner=self.owner).count(), 1)
        configs = [project.character_config for project in created_projects]
        self.assertEqual({config.character_id for config in configs}, {character.pk})
        self.assertEqual(len({config.pk for config in configs}), 3)
        self.assertTrue(all("Light blue blazer" in config.appearance_snapshot or "blazer" in config.appearance_snapshot for config in configs))
