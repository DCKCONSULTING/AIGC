import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import User
from ai.models import (
    Character,
    CharacterMasterReference,
    CharacterView,
    VideoCharacterConfig,
    MasterReferenceStatus,
    Scene,
    VideoProject,
    VideoProjectStatus,
)
from ai.services.characters import (
    front_source_path,
    materialize_character_references,
    sync_project_character,
    uses_master_reference,
)
from ai.services.compiler import compile_scene_prompt
from ai.services.master_character import (
    MASTER_REQUIRED_ERROR,
    MasterCharacterService,
    character_is_video_ready,
)
from ai.services.preflight import PreflightError, preflight_project
from ai.services.snapshots import product_snapshot
from ai.services.video import VideoGenerationService
from brands.models import Brand, Category, Product, ProductImage


def _png(name="face.png", color=(20, 40, 80)) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _png_bytes(color=(90, 20, 20)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


class MasterCharacterTests(APITestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Studio", slug="studio-master")
        self.owner = User.objects.create_user(
            username="master-owner",
            email="master-owner@example.com",
            password="password123",
            name="Owner",
            mobile="0123000101",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        self.other = User.objects.create_user(
            username="master-other",
            email="master-other@example.com",
            password="password123",
            name="Other",
            mobile="0123000102",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(owner=self.owner, category=self.category, name="MiSa Home")
        self.product = Product.objects.create(
            brand=self.brand,
            name="Serum",
            description="Daily face serum.",
            price="89.00",
        )
        ProductImage.objects.create(product=self.product, image=_png("product.png", (10, 120, 40)))
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.owner).key}")

    def _create(self, **extra):
        payload = {
            "brand": self.brand.id,
            "name": "Sarah",
            "gender": "female",
            "appearance_description": extra.pop("appearance_description", "Shoulder-length black hair."),
            "wardrobe_description": extra.pop("wardrobe_description", "Light blue blazer."),
            "default_language": "english",
            "default_tone": "warm",
        }
        payload.update(extra)
        return self.client.post("/api/ai/characters/", payload, format="multipart")

    def _service(self, images=None):
        mock = images or MagicMock()
        if images is None:
            mock.generate_image.return_value = _png_bytes()
        return MasterCharacterService(images=mock), mock

    def _approve(self, character, images=None):
        service, mock = self._service(images)
        record = service.generate(character)
        service.approve(character)
        character.refresh_from_db()
        return record, mock

    def _project(self, character=None, **fields):
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
        payload.update(fields)
        project = VideoProject.objects.create(**payload)
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="Hold the bottle",
            narration="Try this serum.",
            caption="Serum",
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-2",
            order=2,
            visual="Show the texture",
            narration="It absorbs quickly.",
            caption="Glow",
        )
        if character is not None:
            sync_project_character(
                project,
                character.pk,
                language=project.language,
                tone=project.speaking_style,
                gender=project.speaker_gender,
            )
            project.refresh_from_db()
        return project

    def _refs(self, project):
        return VideoGenerationService(
            product_service=MagicMock(),
            reference_service=MagicMock(),
            script_service=MagicMock(),
            images=MagicMock(),
            omni=MagicMock(),
            speech=MagicMock(),
            qa=MagicMock(),
        )._reference_images(project)

    def test_one_front_photo_is_accepted_and_preserved(self):
        created = self._create(appearance_description="", reference_front=_png("face.png"))
        self.assertEqual(created.status_code, 201, created.data)
        character = Character.objects.get(pk=created.data["id"])
        self.assertTrue(character.source_front_image)
        original = Path(character.source_front_image.path)
        self.assertTrue(original.is_file())
        self.assertEqual(character.references.get().view_type, CharacterView.FRONT)
        self.assertEqual(created.data["master_reference_status"], MasterReferenceStatus.PENDING)

        service, mock = self._service()
        service.generate(character)
        character.refresh_from_db()
        self.assertTrue(Path(character.source_front_image.path).is_file())
        self.assertEqual(Path(character.source_front_image.path), original)
        mock.generate_image.assert_called_once()
        kwargs = mock.generate_image.call_args.kwargs
        self.assertEqual(kwargs["system_lock"], "")
        self.assertEqual([str(path) for path in kwargs["reference_images"]], [str(original)])

    def test_no_photo_is_rejected_when_appearance_is_absent(self):
        missing = self._create(appearance_description="", wardrobe_description="")
        self.assertEqual(missing.status_code, 400)

    def test_unsupported_image_is_rejected(self):
        gif = SimpleUploadedFile("face.gif", b"GIF89a\x01\x00\x01\x00", content_type="image/gif")
        rejected = self._create(appearance_description="", reference_front=gif)
        self.assertEqual(rejected.status_code, 400)
        txt = SimpleUploadedFile("face.txt", b"not-an-image", content_type="text/plain")
        rejected_txt = self._create(appearance_description="", reference_front=txt)
        self.assertEqual(rejected_txt.status_code, 400)

    def test_side_photos_are_not_used_as_the_identity_source(self):
        created = self._create(reference_left=_png("left.png", (1, 2, 3)))
        character = Character.objects.get(pk=created.data["id"])
        self.assertFalse(character.source_front_image)
        self.assertIsNone(front_source_path(character))
        service, _mock = self._service()
        with self.assertRaises(Exception):
            service.generate(character)

    def test_generate_moves_pending_processing_ready_and_increments_version(self):
        created = self._create(reference_front=_png("face.png"))
        character = Character.objects.get(pk=created.data["id"])
        seen = []

        def fake_generate(*args, **kwargs):
            character.refresh_from_db()
            seen.append(character.master_reference_status)
            return _png_bytes((12, 34, 56))

        images = MagicMock()
        images.generate_image.side_effect = fake_generate
        service = MasterCharacterService(images=images)
        first = service.generate(character)
        character.refresh_from_db()
        self.assertEqual(seen, [MasterReferenceStatus.PROCESSING])
        self.assertEqual(first.version, 1)
        self.assertEqual(character.master_reference_status, MasterReferenceStatus.PENDING)
        self.assertFalse(character_is_video_ready(character))
        self.assertTrue(first.image)
        self.assertIn("observed_from_photo", first.identity_facts)
        self.assertIn("provided_by_user", first.identity_facts)
        self.assertIn("generated_or_normalized", first.identity_facts)
        self.assertEqual(first.identity_facts["provided_by_user"]["wardrobe"], "Light blue blazer.")
        prompt = images.generate_image.call_args.args[0]
        self.assertIn("preserve the exact identity of the person in the source image", prompt.lower())
        self.assertIn("do not invent shoes", prompt.lower())

        MasterCharacterService(images=images).approve(character)
        character.refresh_from_db()
        self.assertEqual(character.master_reference_status, MasterReferenceStatus.READY)
        self.assertEqual(character.master_reference_version, 1)
        self.assertTrue(character_is_video_ready(character))

        second = MasterCharacterService(images=images).generate(character)
        self.assertEqual(second.version, 2)
        character.refresh_from_db()
        self.assertEqual(character.master_reference_version, 1)
        self.assertEqual(character.current_master_id, first.pk)
        MasterCharacterService(images=images).approve(character)
        character.refresh_from_db()
        self.assertEqual(character.master_reference_version, 2)
        self.assertEqual(character.current_master_id, second.pk)
        self.assertEqual(CharacterMasterReference.objects.filter(character=character).count(), 2)

    def test_gemini_failure_marks_failed_and_keeps_the_original_photo(self):
        created = self._create(reference_front=_png("face.png"))
        character = Character.objects.get(pk=created.data["id"])
        original = character.source_front_image.name
        original_ref = character.references.get().image.name
        images = MagicMock()
        images.generate_image.side_effect = RuntimeError("gemini down")
        with self.assertRaises(Exception):
            MasterCharacterService(images=images).generate(character)
        character.refresh_from_db()
        self.assertEqual(character.master_reference_status, MasterReferenceStatus.FAILED)
        self.assertEqual(character.source_front_image.name, original)
        self.assertEqual(character.references.get().image.name, original_ref)
        self.assertFalse(character.master_reference_image)
        self.assertEqual(character.master_versions.count(), 0)

    def test_api_generate_and_approve(self):
        created = self._create(reference_front=_png("face.png"))
        character_id = created.data["id"]
        with patch("ai.services.master_character.NanoBananaProvider") as provider:
            provider.return_value.generate_image.return_value = _png_bytes()
            generated = self.client.post(f"/api/ai/characters/{character_id}/master-reference/", {}, format="json")
        self.assertEqual(generated.status_code, 200, generated.data)
        self.assertEqual(generated.data["latest_master_version"], 1)
        self.assertTrue(generated.data["latest_master_url"])
        self.assertFalse(generated.data["master_reference_approved"])
        approved = self.client.post(f"/api/ai/characters/{character_id}/master-reference/approve/", {}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertTrue(approved.data["master_reference_approved"])
        self.assertEqual(approved.data["master_reference_status"], MasterReferenceStatus.READY)
        self.assertEqual(approved.data["master_reference_version"], 1)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.other).key}")
        hidden = self.client.post(f"/api/ai/characters/{character_id}/master-reference/", {}, format="json")
        self.assertEqual(hidden.status_code, 404)

    def test_video_snapshot_freezes_the_approved_master_version(self):
        created = self._create(reference_front=_png("face.png"))
        character = Character.objects.get(pk=created.data["id"])
        first, _mock = self._approve(character)
        project = self._project(character)
        frozen = dict(project.character_config.identity_snapshot)
        self.assertEqual(frozen["master_reference_version"], 1)
        self.assertEqual(frozen["master_reference_image"], character.master_reference_image.name)
        self.assertTrue(uses_master_reference(project.character_config))

        images = MagicMock()
        images.generate_image.return_value = _png_bytes((1, 2, 3))
        MasterCharacterService(images=images).generate(character)
        MasterCharacterService(images=images).approve(character)
        character.appearance_description = "A different person."
        character.save(update_fields=["appearance_description", "updated_at"])
        materialize_character_references(project)
        project.character_config.refresh_from_db()
        self.assertEqual(project.character_config.identity_snapshot["master_reference_version"], 1)
        self.assertEqual(project.character_config.identity_snapshot["master_reference_image"], frozen["master_reference_image"])
        self.assertEqual(project.character_config.appearance_snapshot, frozen["appearance"])
        self.assertNotEqual(character.master_reference_version, 1)

    def test_omni_uses_the_same_master_for_every_scene_and_skips_old_angles(self):
        created = self._create(
            reference_front=_png("face.png"),
            reference_left=_png("left.png", (9, 9, 9)),
            reference_right=_png("right.png", (8, 8, 8)),
        )
        character = Character.objects.get(pk=created.data["id"])
        self._approve(character)
        project = self._project(character)
        refs = self._refs(project)
        product_path = self.product.images.first().image.path
        master_path = character.master_reference_image.path
        self.assertEqual(refs[0], product_path)
        self.assertEqual(Path(refs[1]).resolve(), Path(master_path).resolve())
        self.assertEqual(len(refs), 2)
        self.assertFalse(any("left" in path or "right" in path for path in refs))
        self.assertEqual(self._refs(project), refs)

        prompts = [compile_scene_prompt(scene, project) for scene in project.scenes.order_by("order")]
        self.assertEqual(len(prompts), 2)
        for prompt, visual in zip(prompts, ["Hold the bottle", "Show the texture"]):
            self.assertIn("CHARACTER IDENTITY", prompt)
            self.assertIn("CHARACTER BEHAVIOR", prompt)
            self.assertIn("CHARACTER IDENTITY — LOCKED", prompt)
            self.assertIn("The character identity is locked.", prompt)
            self.assertIn("The character name is only an identifier", prompt)
            self.assertNotIn("Character: Sarah", prompt)
            self.assertIn(visual, prompt)
        self.assertEqual(
            project.character_config.identity_snapshot["master_reference_image"],
            character.master_reference_image.name,
        )

    def test_existing_videos_keep_stored_multi_photo_references(self):
        created = self._create(
            reference_front=_png("face.png"),
            reference_left=_png("left.png", (9, 9, 9)),
            reference_right=_png("right.png", (8, 8, 8)),
        )
        character = Character.objects.get(pk=created.data["id"])
        project = self._project(character, status=VideoProjectStatus.READY_FOR_REVIEW)
        snapshot = list(project.character_config.reference_snapshot)
        self.assertFalse(uses_master_reference(project.character_config))
        legacy_refs = self._refs(project)
        self.assertGreaterEqual(len(legacy_refs), 2)

        self._approve(character)
        materialize_character_references(project)
        project.character_config.refresh_from_db()
        self.assertEqual(list(project.character_config.reference_snapshot), snapshot)
        self.assertFalse(uses_master_reference(project.character_config))
        self.assertEqual(self._refs(project), legacy_refs)

        with patch("ai.services.preflight.require_omni_key"):
            try:
                preflight_project(project)
            except PreflightError as exc:
                self.assertNotIn(MASTER_REQUIRED_ERROR, exc.errors)

    def test_new_generation_is_blocked_without_an_approved_master(self):
        created = self._create(reference_front=_png("face.png"))
        character = Character.objects.get(pk=created.data["id"])
        project = self._project(character)
        with patch("ai.services.preflight.require_omni_key"):
            with self.assertRaises(PreflightError) as exc:
                preflight_project(project)
        self.assertIn(MASTER_REQUIRED_ERROR, exc.exception.errors)

        self._approve(character)
        with patch("ai.services.preflight.require_omni_key"):
            try:
                preflight_project(project)
            except PreflightError as exc:
                self.assertNotIn(MASTER_REQUIRED_ERROR, exc.errors)

    def test_generate_character_skips_the_master_requirement(self):
        created = self._create(reference_front=_png("face.png"))
        character = Character.objects.get(pk=created.data["id"])
        project = self._project(character, status=VideoProjectStatus.FAILED)
        brief = dict(project.creative_brief or {})
        brief["generate_character"] = True
        brief["character_id"] = None
        project.creative_brief = brief
        project.save(update_fields=["creative_brief", "updated_at"])
        sync_project_character(
            project,
            None,
            language=project.language,
            tone=project.speaking_style,
            gender=project.speaker_gender,
        )
        project.refresh_from_db()
        self.assertFalse(VideoCharacterConfig.objects.filter(project=project).exists())
        with patch("ai.services.preflight.require_omni_key"):
            try:
                preflight_project(project)
            except PreflightError as exc:
                self.assertNotIn(MASTER_REQUIRED_ERROR, exc.errors)
