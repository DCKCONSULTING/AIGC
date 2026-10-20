import base64
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import User
from ai.exceptions import ProviderError
from ai.models import Scene, VideoProject, VideoProjectStatus
from ai.providers.google.omni import GeminiOmniProvider
from ai.services.video import VideoGenerationService
from brands.models import Brand, Category, Product, ProductImage

URI = "https://generativelanguage.googleapis.com/v1beta/files/abc123:download?alt=media"
INTERACTION_ID = "v1_interaction"
FILE_ID = "files/abc123"


def _png() -> SimpleUploadedFile:
    return SimpleUploadedFile("shot.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, content_type="image/png")


class _Video:
    def __init__(self, uri="", data=None):
        self.uri = uri
        self.data = data


class _Interaction:
    def __init__(self, output_video, interaction_id=INTERACTION_ID):
        self.id = interaction_id
        self.status = "completed"
        self.output_video = output_video


def _video(uri=URI, data=None):
    return _Video(uri=uri, data=data)


def _file(state, message=""):
    error = MagicMock(message=message) if message else None
    return MagicMock(state=state, error=error)


@override_settings(GEMINI_API_KEY="test-key", GOOGLE_API_KEY="test-key", GEMINI_OMNI_MODEL="gemini-omni-1.1-flash")
class OmniFileRetrievalTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="omni-files",
            email="omni-files@example.com",
            password="password123",
            name="Omni Files",
            mobile="0123000000",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        category = Category.objects.create(name="Omni Files", slug="omni-files")
        brand = Brand.objects.create(owner=self.owner, category=category, name="Omni Brand")
        self.product = Product.objects.create(brand=brand, name="Crisp", description="A crisp.", price="9.90")
        ProductImage.objects.create(product=self.product, image=_png())

    def _project(self) -> tuple[VideoProject, Scene]:
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            status=VideoProjectStatus.GENERATING_VIDEO,
            creative_brief={"schema_version": 2},
            duration_seconds=3,
        )
        scene = Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="A red ball on a white table.",
            narration="Hello",
            caption="Hello",
            duration=3,
        )
        return project, scene

    def _run(self, client):
        project, scene = self._project()
        with (
            patch("ai.providers.google.omni.get_genai_client", return_value=client),
            patch("ai.services.video.time.sleep"),
            patch("ai.services.video.inspect_audio", return_value={"audible": True, "reason": ""}),
        ):
            VideoGenerationService(omni=GeminiOmniProvider())._create_videos(project)
        scene.refresh_from_db()
        project.refresh_from_db()
        return project, scene

    def test_uri_response_polls_files_and_saves_clip(self):
        client = MagicMock()
        client.interactions.create.return_value = _Interaction(_video())
        client.interactions.get.side_effect = AssertionError("interactions.get must not be called")
        client.files.get.side_effect = [_file("PROCESSING"), _file("PROCESSING"), _file("ACTIVE")]

        def download(*, file, destination, config=None):
            from pathlib import Path

            Path(destination).write_bytes(b"mp4-omni")

        client.files.download.side_effect = download
        project, scene = self._run(client)
        self.assertEqual(scene.generation_status, "completed")
        self.assertEqual(scene.provider_request_id, INTERACTION_ID)
        self.assertEqual(scene.metadata.get("omni_file_id"), FILE_ID)
        self.assertEqual(scene.metadata.get("omni_interaction_id"), INTERACTION_ID)
        self.assertNotEqual(scene.provider_request_id, FILE_ID)
        self.assertEqual(scene.video_clip.read(), b"mp4-omni")
        self.assertEqual(project.provider_request_id, INTERACTION_ID)
        client.interactions.get.assert_not_called()
        self.assertEqual(client.interactions.create.call_count, 1)
        self.assertGreaterEqual(client.files.get.call_count, 3)
        client.files.get.assert_any_call(name=FILE_ID)
        client.files.download.assert_called_once()
        self.assertEqual(client.files.download.call_args.kwargs["file"], URI)
        payload = client.interactions.create.call_args.kwargs
        self.assertEqual(payload["response_format"]["delivery"], "uri")
        self.assertEqual(payload["response_format"]["aspect_ratio"], "9:16")
        self.assertEqual(payload["model"], "gemini-omni-1.1-flash")
        self.assertFalse(payload["background"])

    def test_files_failed_does_not_create_another_interaction(self):
        client = MagicMock()
        client.interactions.create.return_value = _Interaction(_video())
        client.files.get.side_effect = [_file("PROCESSING"), _file("FAILED", "file processing failed")]
        with self.assertRaises(ProviderError) as ctx:
            project, scene = self._run(client)
        self.assertIn("file processing failed", str(ctx.exception))
        scene = Scene.objects.get(project__product=self.product)
        self.assertEqual(scene.generation_status, "failed")
        self.assertEqual(scene.provider_request_id, INTERACTION_ID)
        self.assertEqual(scene.metadata.get("omni_file_id"), FILE_ID)
        self.assertFalse(scene.video_clip)
        self.assertEqual(client.interactions.create.call_count, 1)
        client.interactions.get.assert_not_called()

    def test_inline_video_skips_files_and_interaction_get(self):
        encoded = base64.b64encode(b"inline-mp4").decode("ascii")
        client = MagicMock()
        client.interactions.create.return_value = _Interaction(_video(uri="", data=encoded))
        client.interactions.get.side_effect = AssertionError("interactions.get must not be called")
        project, scene = self._run(client)
        self.assertEqual(scene.generation_status, "completed")
        self.assertEqual(scene.video_clip.read(), b"inline-mp4")
        self.assertEqual(scene.provider_request_id, INTERACTION_ID)
        self.assertEqual(scene.metadata.get("omni_file_id") or "", "")
        client.files.get.assert_not_called()
        client.files.download.assert_not_called()
        client.interactions.get.assert_not_called()
        self.assertEqual(client.interactions.create.call_count, 1)

    def test_interaction_get_400_is_not_used(self):
        class InvalidRequest(Exception):
            status_code = 400

            def __str__(self):
                return "400 INVALID_REQUEST"

        client = MagicMock()
        client.interactions.create.return_value = _Interaction(_video())
        client.interactions.get.side_effect = InvalidRequest("400 INVALID_REQUEST")
        client.files.get.side_effect = [_file("PROCESSING"), _file("ACTIVE")]

        def download(*, file, destination, config=None):
            from pathlib import Path

            Path(destination).write_bytes(b"mp4-omni")

        client.files.download.side_effect = download
        project, scene = self._run(client)
        self.assertEqual(scene.generation_status, "completed")
        self.assertEqual(scene.video_clip.read(), b"mp4-omni")
        client.interactions.get.assert_not_called()
        client.files.get.assert_any_call(name=FILE_ID)

    def test_missing_uri_and_data_fails_without_a_clip(self):
        client = MagicMock()
        client.interactions.create.return_value = _Interaction(_video(uri="", data=None))
        with self.assertRaises(ProviderError) as ctx:
            self._run(client)
        self.assertIn("no output_video URI or inline data", str(ctx.exception))
        self.assertEqual(ctx.exception.code, "MISSING_VIDEO_OUTPUT")
        scene = Scene.objects.get(project__product=self.product)
        self.assertEqual(scene.generation_status, "failed")
        self.assertEqual(scene.failure_code, "MISSING_VIDEO_OUTPUT")
        self.assertEqual(scene.provider_request_id, INTERACTION_ID)
        self.assertFalse(scene.video_clip)
        self.assertEqual(client.interactions.create.call_count, 1)
        client.files.get.assert_not_called()
        client.interactions.get.assert_not_called()

    def test_download_failure_does_not_create_another_interaction(self):
        client = MagicMock()
        client.interactions.create.return_value = _Interaction(_video())
        client.files.get.return_value = _file("ACTIVE")
        client.files.download.side_effect = RuntimeError("download failed")
        with self.assertRaises(ProviderError) as ctx:
            self._run(client)
        self.assertIn("download failed", str(ctx.exception).lower())
        scene = Scene.objects.get(project__product=self.product)
        self.assertEqual(scene.generation_status, "failed")
        self.assertEqual(scene.provider_request_id, INTERACTION_ID)
        self.assertEqual(scene.metadata.get("omni_file_id"), FILE_ID)
        self.assertFalse(scene.video_clip)
        self.assertEqual(client.interactions.create.call_count, 1)
        self.assertGreaterEqual(client.files.download.call_count, 1)
        client.interactions.get.assert_not_called()
