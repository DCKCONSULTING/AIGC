from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile
from django.test import TestCase

from accounts.models import User
from ai.models import (
    Character,
    CharacterReferenceImage,
    LanguageChoice,
    Scene,
    StyleChoice,
    VideoAsset,
    VideoCharacterConfig,
    VideoProject,
    VideoProjectStatus,
)
from ai.services.identity_qa import (
    IDENTITY_PASS_THRESHOLD,
    decide_audio,
    decide_identity,
    project_gates_pass,
    scenes_requiring_regeneration,
)
from ai.services.qa import QAService, release_blocking_issues
from ai.services.video import VideoGenerationService
from brands.models import Brand, Category, Product


def _passed_identity(**extra):
    payload = {
        "required": True,
        "status": "passed",
        "confidence": 0.95,
        "comparison_performed": True,
        "face_detected": True,
    }
    payload.update(extra)
    return payload


def _passed_audio(**extra):
    payload = {"required": True, "status": "passed", "speech_detected": True, "has_audio_stream": True}
    payload.update(extra)
    return payload


class IdentityDecisionTest(TestCase):
    def test_threshold_constant(self):
        self.assertEqual(IDENTITY_PASS_THRESHOLD, 0.90)

    def test_zero_confidence_fails(self):
        result = decide_identity(confidence=0, comparison_performed=True, face_detected=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["confidence"], 0.0)

    def test_null_confidence_fails(self):
        result = decide_identity(confidence=None, comparison_performed=True, face_detected=True)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["confidence"])

    def test_comparison_not_performed_fails(self):
        result = decide_identity(confidence=0.95, comparison_performed=False, face_detected=True)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["comparison_performed"])
        self.assertIsNone(result["confidence"])

    def test_missing_face_fails(self):
        result = decide_identity(confidence=0.95, comparison_performed=True, face_detected=False)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["confidence"], 0.0)
        self.assertIn("not detected", result["reason"].lower())

    def test_below_threshold_fails(self):
        result = decide_identity(confidence=0.89, comparison_performed=True, face_detected=True)
        self.assertEqual(result["status"], "failed")

    def test_threshold_passes(self):
        result = decide_identity(confidence=0.90, comparison_performed=True, face_detected=True)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["confidence"], 0.90)

    def test_high_confidence_passes(self):
        result = decide_identity(confidence=0.95, comparison_performed=True, face_detected=True)
        self.assertEqual(result["status"], "passed")

    def test_ambiguous_face_fails(self):
        result = decide_identity(
            confidence=0.99,
            comparison_performed=True,
            face_detected=True,
            ambiguous=True,
        )
        self.assertEqual(result["status"], "failed")


class AudioDecisionTest(TestCase):
    def test_missing_stream_fails(self):
        result = decide_audio(narration_required=True, has_audio_stream=False, speech_detected=False)
        self.assertEqual(result["status"], "failed")
        self.assertIn("silent or missing", result["reason"])

    def test_stream_without_speech_fails(self):
        result = decide_audio(
            narration_required=True,
            has_audio_stream=True,
            speech_detected=False,
            silent=False,
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("not detected", result["reason"])

    def test_unverified_speech_fails(self):
        result = decide_audio(
            narration_required=True,
            has_audio_stream=True,
            speech_detected=None,
            verification_available=False,
            silent=False,
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("could not verify", result["reason"])

    def test_detected_speech_passes(self):
        result = decide_audio(narration_required=True, speech_detected=True)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["speech_detected"])


class ProjectGateTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Identity", slug="identity-qa")
        owner = User.objects.create_user(
            username="identity-owner",
            email="identity@example.com",
            password="password123",
            name="Owner",
            mobile="0123000099",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        brand = Brand.objects.create(owner=owner, category=category, name="MiSa")
        self.product = Product.objects.create(
            brand=brand,
            name="Penang Air Crisp",
            description="Crisp.",
            price="12.00",
        )
        self.owner = owner
        self.brand = brand

    def _project(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            status=VideoProjectStatus.READY_FOR_REVIEW,
            creative_brief={"schema_version": 2},
            selected_concept_id="concept-1",
        )
        character = Character.objects.create(
            owner=self.owner,
            brand=self.brand,
            name="Mike",
            gender="male",
        )
        VideoCharacterConfig.objects.create(
            project=project,
            character=character,
            language=LanguageChoice.CONVERSATIONAL_BM,
            tone=StyleChoice.WARM,
            gender="male",
            identity_snapshot={"id": character.pk, "name": "Mike"},
            reference_snapshot=[],
        )
        keys = []
        for index in range(1, 5):
            scene = Scene.objects.create(
                project=project,
                scene_key=f"scene-{index}",
                order=index,
                title=f"Scene {index}",
                visual="Presenter",
                narration="Hello from Mike.",
                caption="Hello",
                duration=4,
            )
            scene.video_clip.save(f"scene-{index}.mp4", ContentFile(f"clip-{index}".encode()), save=True)
            keys.append(scene)
        return project, keys

    def test_one_identity_failure_blocks_project_and_approval(self):
        gates = [
            {"identity": _passed_identity(), "audio": _passed_audio()},
            {"identity": _passed_identity(confidence=0.93), "audio": _passed_audio()},
            {"identity": _passed_identity(status="failed", confidence=0.71), "audio": _passed_audio()},
            {"identity": _passed_identity(), "audio": _passed_audio()},
        ]
        self.assertFalse(project_gates_pass(gates))
        blocked = release_blocking_issues(
            [{"name": "character_identity", "status": "failed", "detail": "Scene 3", "scene_id": "scene-3"}],
            has_preview=True,
        )
        self.assertEqual(blocked[0]["name"], "character_identity")
        self.assertEqual(QAService()._roll_up([{"status": "passed"}, {"status": "failed"}]), "failed")

    def test_one_audio_failure_blocks_project_and_approval(self):
        gates = [
            {"identity": _passed_identity(), "audio": _passed_audio()},
            {"identity": _passed_identity(), "audio": _passed_audio(status="failed", speech_detected=False)},
        ]
        self.assertFalse(project_gates_pass(gates))
        blocked = release_blocking_issues(
            [{"name": "scene_narration", "status": "failed", "detail": "Silent", "scene_id": "scene-4"}],
            has_preview=True,
        )
        self.assertEqual(blocked[0]["name"], "scene_narration")

    def test_failed_scene_regenerates_only_that_scene(self):
        project, scenes = self._project()
        for scene, status, confidence in (
            (scenes[0], "passed", 0.96),
            (scenes[1], "passed", 0.93),
            (scenes[2], "failed", 0.71),
            (scenes[3], "passed", 0.95),
        ):
            meta = dict(scene.metadata or {})
            meta["identity"] = _passed_identity(status=status, confidence=confidence)
            meta["audio"] = _passed_audio()
            scene.metadata = meta
            scene.save(update_fields=["metadata"])
        before = {scene.scene_key: scene.video_clip.name for scene in scenes}
        failed_ids = scenes_requiring_regeneration(project)
        self.assertEqual(failed_ids, [scenes[2].pk])

        with (
            patch.object(VideoGenerationService, "_refresh_snapshot"),
            patch.object(VideoGenerationService, "_create_images") as images,
            patch.object(VideoGenerationService, "_create_videos") as videos,
            patch.object(VideoGenerationService, "_create_voice"),
            patch.object(VideoGenerationService, "_assemble"),
            patch.object(VideoGenerationService, "_quality"),
            patch.object(VideoGenerationService, "_recommend"),
        ):
            VideoGenerationService().regenerate_scenes(project.pk, failed_ids)

        rendered = videos.call_args.kwargs.get("scenes") or videos.call_args.args[1]
        self.assertEqual([scene.scene_key for scene in rendered], ["scene-3"])
        if images.called:
            imaged = images.call_args.kwargs.get("scenes") or images.call_args.args[1]
            self.assertEqual([scene.scene_key for scene in imaged], ["scene-3"])
        project.refresh_from_db()
        self.assertNotEqual(project.status, VideoProjectStatus.APPROVED)
        for scene in scenes:
            scene.refresh_from_db()
            if scene.scene_key != "scene-3":
                self.assertEqual(scene.video_clip.name, before[scene.scene_key])
                self.assertEqual(Path(scene.video_clip.path).read_bytes(), f"clip-{scene.order}".encode())

    def _reference(self, character, payload: bytes, view="front", order=0):
        ref = CharacterReferenceImage(character=character, view_type=view, sort_order=order)
        ref.image.save(f"{view}.png", ContentFile(payload), save=True)
        return ref

    def test_stored_reference_bytes_are_what_identity_qa_loads(self):
        from ai.services.identity_qa import evaluate_scene_identity, load_reference_bytes

        project, scenes = self._project()
        payload = b"\x89PNG\r\n\x1a\nmike-front"
        ref = self._reference(project.character_config.character, payload)
        self.assertEqual(load_reference_bytes(ref), payload)
        scene = scenes[0]
        scene.video_clip.save("generated.png", ContentFile(b"\x89PNG\r\n\x1a\ngenerated"), save=True)
        config = project.character_config
        config.reference_snapshot = [{"id": ref.pk, "view_type": "front", "storage_name": ref.image.name}]
        config.save(update_fields=["reference_snapshot"])
        gemini = MagicMock()
        gemini.generate_json.return_value = {
            "face_detected": True,
            "face_count": 1,
            "identified": True,
            "ambiguous": False,
            "confidence": 0,
        }
        result = evaluate_scene_identity(project, scene, config, gemini)
        sent = gemini.generate_json.call_args.kwargs["files"]
        self.assertEqual(Path(sent[0]).read_bytes(), payload)
        self.assertEqual(result["reference_image_id"], ref.pk)
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["status"], "failed")

    def test_missing_reference_file_fails_without_a_score(self):
        from ai.services.identity_qa import REFERENCE_UNAVAILABLE, evaluate_scene_identity, load_reference_bytes

        project, scenes = self._project()
        ref = CharacterReferenceImage(character=project.character_config.character, view_type="front")
        ref.image.name = "ai/characters/2026/09/IMG_7070_NNuN6O4.JPG"
        ref.save()
        with self.assertRaises(FileNotFoundError):
            load_reference_bytes(ref)
        gemini = MagicMock()
        result = evaluate_scene_identity(project, scenes[0], project.character_config, gemini)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["confidence"])
        self.assertEqual(result["reason"], REFERENCE_UNAVAILABLE)
        self.assertIn("IMG_7070_NNuN6O4.JPG", result["reference_error"])
        self.assertFalse(result["comparison_performed"])
        gemini.generate_json.assert_not_called()

    def test_invalid_storage_path_fails_and_records_the_path(self):
        from ai.services.identity_qa import REFERENCE_UNAVAILABLE, evaluate_scene_identity

        project, scenes = self._project()
        ref = CharacterReferenceImage(character=project.character_config.character, view_type="front")
        ref.image.name = "/tmp/not-a-character-reference.jpg"
        ref.save()
        gemini = MagicMock()
        result = evaluate_scene_identity(project, scenes[0], project.character_config, gemini)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], REFERENCE_UNAVAILABLE)
        self.assertIsNone(result["confidence"])
        self.assertIn("/tmp/not-a-character-reference.jpg", result["reference_error"])
        gemini.generate_json.assert_not_called()

    def test_multiple_references_use_this_characters_front_photo(self):
        from ai.services.identity_qa import evaluate_scene_identity

        project, scenes = self._project()
        character = project.character_config.character
        side = self._reference(character, b"side-view", view="left", order=2)
        front = self._reference(character, b"front-view", view="front", order=1)
        other = Character.objects.create(owner=self.owner, brand=self.brand, name="Someone Else", gender="female")
        stranger = self._reference(other, b"stranger", view="front", order=0)
        scene = scenes[0]
        scene.video_clip.save("generated.png", ContentFile(b"generated-face"), save=True)
        gemini = MagicMock()
        gemini.generate_json.return_value = {
            "face_detected": True,
            "face_count": 1,
            "identified": True,
            "ambiguous": False,
            "confidence": 0.91,
        }
        result = evaluate_scene_identity(project, scene, project.character_config, gemini)
        sent = [Path(path).read_bytes() for path in gemini.generate_json.call_args.kwargs["files"][:-1]]
        self.assertEqual(sent[0], b"front-view")
        self.assertIn(b"side-view", sent)
        self.assertNotIn(b"stranger", sent)
        self.assertEqual(result["reference_image_id"], front.pk)
        self.assertNotEqual(result["reference_image_id"], stranger.pk)
        self.assertNotEqual(result["reference_image_id"], side.pk)
        self.assertEqual(result["status"], "passed")

    def test_a_generated_still_is_not_the_character_reference(self):
        from ai.services.identity_qa import REFERENCE_UNAVAILABLE, evaluate_scene_identity

        project, scenes = self._project()
        still = VideoAsset.objects.create(
            project=project,
            kind=VideoAsset.Kind.IMAGE,
            prompt="presenter-identity",
            metadata={"presenter_reference": True, "presenter_identity": True, "angle": "front"},
        )
        still.file.save("presenter-identity.png", ContentFile(b"\x89PNG\r\n\x1a\n"), save=True)
        gemini = MagicMock()
        result = evaluate_scene_identity(project, scenes[0], project.character_config, gemini)
        self.assertFalse(result["comparison_performed"])
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["confidence"])
        self.assertEqual(result["reason"], REFERENCE_UNAVAILABLE)
        gemini.generate_json.assert_not_called()
