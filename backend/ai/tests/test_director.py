from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import User
from ai.models import Scene, VideoProject, VideoProjectStatus
from ai.services.amendments import AmendmentService
from ai.services.compiler import compile_scene_prompt
from ai.services.director import (
    DirectorService,
    brief_from_legacy,
    commercial_cta,
    compose_merchant_instructions,
    extra_instruction_requirement,
    format_approved_price,
    normalize_brief,
    suppress_price,
    suppress_website,
)
from ai.services.snapshots import product_snapshot
from ai.services.templates import suggest_templates
from brands.models import Brand, Category, Product, ProductImage


def _png() -> SimpleUploadedFile:
    return SimpleUploadedFile("shot.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, content_type="image/png")


CONCEPTS = {
    "concepts": [
        {
            "id": "ugc",
            "title": "Busy kitchen fix",
            "style": "ugc",
            "strategy": "Problem then solution",
            "hook": "Dinner in 10 minutes?",
            "narrative": "A parent finds a faster way to cook.",
            "cta": "Shop now",
            "why_it_works": "Feels real",
            "estimated_duration": 30,
            "scenes": [
                {
                    "scene_key": "scene-1",
                    "order": 1,
                    "title": "Hook",
                    "duration": 10,
                    "shot_description": "Parent in a kitchen",
                    "voice_over": "Need dinner fast?",
                    "on_screen_caption": "Dinner rush",
                },
                {
                    "scene_key": "scene-2",
                    "order": 2,
                    "title": "Offer",
                    "duration": 20,
                    "shot_description": "Product on the counter",
                    "voice_over": "Serum at RM39.90",
                    "on_screen_caption": "RM39.90",
                },
            ],
        },
        {
            "id": "demo",
            "title": "Show it working",
            "style": "demonstration",
            "strategy": "Direct demo",
            "hook": "See it work",
            "narrative": "Hands demonstrate the product.",
            "cta": "Shop now",
            "why_it_works": "Clear proof",
            "estimated_duration": 30,
            "scenes": [
                {
                    "scene_key": "scene-1",
                    "duration": 15,
                    "shot_description": "Hands open the bottle",
                    "voice_over": "One pump is enough.",
                    "on_screen_caption": "Easy use",
                },
                {
                    "scene_key": "scene-2",
                    "duration": 15,
                    "shot_description": "Product close-up",
                    "voice_over": "RM39.90",
                    "on_screen_caption": "RM39.90",
                },
            ],
        },
        {
            "id": "lifestyle",
            "title": "Morning routine",
            "style": "lifestyle",
            "strategy": "Daily moment",
            "hook": "Start fresh",
            "narrative": "A calm morning with the product.",
            "cta": "Follow us",
            "why_it_works": "Aspirational",
            "estimated_duration": 30,
            "scenes": [
                {
                    "scene_key": "scene-1",
                    "duration": 12,
                    "shot_description": "Sunlit room",
                    "voice_over": "A simple morning.",
                    "on_screen_caption": "Morning",
                },
                {
                    "scene_key": "scene-2",
                    "duration": 18,
                    "shot_description": "Smile to camera",
                    "voice_over": "Try Serum today.",
                    "on_screen_caption": "Shop now",
                },
            ],
        },
    ]
}


class DirectorServiceTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Beauty", slug="beauty")
        self.owner = User.objects.create_user(
            username="director",
            email="director@example.com",
            password="password123",
            name="Director",
            mobile="0123000000",
            location="KL",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Dck Beauty",
            description="Skincare",
            location="KL",
        )
        self.product = Product.objects.create(
            brand=self.brand,
            name="Serum",
            description="Daily hydrating serum",
            price="39.90",
            variants=["30ml"],
            approved_claims=["hydrating"],
        )
        self.project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            duration_seconds=30,
            status=VideoProjectStatus.DRAFT,
        )

    def test_normalize_brief_does_not_invent_price(self):
        brief = normalize_brief(
            {
                "objective": "buy",
                "customer": "Busy parents",
                "main_benefit": "Quick meals",
                "duration": 45,
            },
            self.project,
        )
        self.assertEqual(brief["objective"], "buy")
        self.assertEqual(brief["duration"], 45)
        self.assertEqual(brief["price"], "39.90")
        self.assertEqual(brief["original_price"], "39.90")
        self.assertEqual(brief["product_truth"]["price"], "39.90")

    def test_normalize_brief_keeps_generate_character(self):
        brief = normalize_brief(
            {
                "objective": "buy",
                "customer": "Busy parents",
                "main_benefit": "Quick meals",
                "duration": 45,
                "generate_character": True,
                "character_id": 12,
            },
            self.project,
        )
        self.assertTrue(brief["generate_character"])
        self.assertIsNone(brief["character_id"])

    def test_commercial_cta_keeps_usd_and_original_price(self):
        self.assertEqual(format_approved_price("USD499"), "USD499")
        self.assertEqual(format_approved_price("499.00"), "RM499.00")
        self.assertEqual(format_approved_price("RM169"), "RM169")
        usd_only = commercial_cta(
            {"objective": "buy", "offer_price": "USD499", "original_price": "499.00"},
            {"name": "FULGEO Managed Visibility Package"},
            "conversational_bm",
        )
        self.assertIn("USD499", usd_only)
        self.assertNotIn("RMUSD", usd_only)
        both = commercial_cta(
            {"objective": "buy", "original_price": "RM189", "offer_price": "RM169"},
            {"name": "Air Fryer"},
            "english",
        )
        self.assertIn("RM189", both)
        self.assertIn("RM169", both)

    def test_legacy_brief_from_old_project(self):
        self.project.merchant_instructions = "Buat video BM santai."
        self.project.creative_brief = {"hook": "Hi", "audience": "Parents"}
        self.project.save()
        brief = brief_from_legacy(self.project)
        self.assertEqual(brief["customer"], "Parents")
        self.assertIn("BM santai", brief["legacy_instructions"])

    def test_stamp_continuity_locks_same_location_chain(self):
        for index, title in enumerate(("Hook", "Demo", "CTA"), start=1):
            Scene.objects.create(
                project=self.project,
                scene_key=f"scene-{index}",
                order=index,
                title=title,
                duration=5,
                metadata={"location": "modern kitchen", "lighting": "warm indoor"},
            )
        DirectorService()._stamp_continuity(self.project)
        scenes = list(self.project.scenes.order_by("order"))
        self.assertFalse((scenes[0].metadata or {}).get("requires_previous_scene_continuity"))
        self.assertFalse((scenes[1].metadata or {}).get("requires_previous_scene_continuity"))
        self.assertFalse((scenes[2].metadata or {}).get("requires_previous_scene_continuity"))
        self.assertTrue((scenes[1].metadata or {}).get("location_locked"))
        self.assertEqual((self.project.creative_brief or {}).get("continuity_state", {}).get("location"), "modern kitchen")

    def test_stamp_continuity_breaks_on_location_change(self):
        Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            order=1,
            duration=5,
            metadata={"location": "modern kitchen"},
        )
        Scene.objects.create(
            project=self.project,
            scene_key="scene-2",
            order=2,
            duration=5,
            metadata={"location": "bedroom", "transition": "cut to another room"},
        )
        DirectorService()._stamp_continuity(self.project)
        second = self.project.scenes.get(scene_key="scene-2")
        self.assertFalse((second.metadata or {}).get("requires_previous_scene_continuity"))

    def test_continuity_dependents_stop_at_independent_scene(self):
        from ai.services.director import continuity_dependents, mark_continuity_stale

        first = Scene.objects.create(project=self.project, scene_key="s1", order=1, duration=5, metadata={})
        second = Scene.objects.create(
            project=self.project,
            scene_key="s2",
            order=2,
            duration=5,
            metadata={"requires_previous_scene_continuity": True},
        )
        Scene.objects.create(
            project=self.project,
            scene_key="s3",
            order=3,
            duration=5,
            metadata={"requires_previous_scene_continuity": False},
        )
        dependents = continuity_dependents(self.project, first)
        self.assertEqual([item.scene_key for item in dependents], ["s2"])
        marked = mark_continuity_stale(dependents)
        second.refresh_from_db()
        self.assertTrue((second.metadata or {}).get("continuity_invalid"))
        self.assertEqual(marked[0].pk, second.pk)

    def test_extra_instruction_is_required_when_present(self):
        self.assertEqual(extra_instruction_requirement({}), "")
        self.assertEqual(extra_instruction_requirement({"legacy_instructions": "  "}), "")
        required = extra_instruction_requirement({"legacy_instructions": "Show the red lid first."})
        self.assertIn("REQUIRED extra instruction", required)
        self.assertIn("Show the red lid first.", required)
        composed = compose_merchant_instructions(
            {
                "objective": "buy",
                "customer": "Parents",
                "main_benefit": "Quick meals",
                "legacy_instructions": "Show the red lid first.",
            }
        )
        self.assertIn("Show the red lid first.", composed)
        self.assertIn("REQUIRED extra instruction", composed)

    def test_templates_are_data_driven(self):
        picked = suggest_templates({"objective": "buy", "offer_text": "RM169"}, category="Kitchen")
        self.assertEqual(len(picked), 3)
        self.assertEqual(len({item["id"] for item in picked}), 3)
        ten = suggest_templates({"objective": "buy"}, count=10)
        self.assertEqual(len(ten), 10)
        self.assertEqual(len({item["id"] for item in ten}), 10)

    def test_compiler_includes_locks_and_product_truth(self):
        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            visual="Product on table",
            narration="Harga RM39.90",
            caption="RM39.90",
            duration=5,
            metadata={"product_locked": True, "presenter_locked": True},
        )
        self.project.creative_brief = normalize_brief(
            {
                "objective": "buy",
                "must_remain_exact": ["product_appearance"],
                "must_not_show": "No kids",
                "original_price": "RM189",
                "offer_price": "USD499",
            },
            self.project,
        )
        prompt = compile_scene_prompt(scene, self.project)
        self.assertIn("PRODUCT TRUTH", prompt)
        self.assertIn("39.90", prompt)
        self.assertIn("USD499", prompt)
        self.assertIn("RM189", prompt)
        self.assertNotIn("RMUSD", prompt)
        self.assertIn("visually identical", prompt)
        self.assertIn("original product photographs", prompt)
        self.assertIn("AUDIO", prompt)
        self.assertIn("same presenter", prompt)
        self.assertIn("Must not show", prompt)
        self.assertNotIn("SEEDANCE_API_KEY", prompt)

    def test_protects_invented_price_in_concepts(self):
        raw = {
            "concepts": [
                {
                    **CONCEPTS["concepts"][0],
                    "cta": "Was RM999 now RM12",
                    "scenes": [
                        {
                            "scene_key": "scene-1",
                            "duration": 30,
                            "shot_description": "x",
                            "voice_over": "Only RM12 today",
                            "on_screen_caption": "RM12",
                        }
                    ],
                },
                CONCEPTS["concepts"][1],
                CONCEPTS["concepts"][2],
            ]
        }
        concepts = DirectorService()._normalize_concepts(
            raw["concepts"],
            self.project,
            normalize_brief({"offer_price": "39.90"}, self.project),
            [],
            30,
        )
        self.assertNotIn("RM12", concepts[0]["cta"])
        self.assertNotIn("RM12", concepts[0]["scenes"][0]["on_screen_caption"])
        self.assertIn("39.90", concepts[0]["scenes"][0]["on_screen_caption"])

    def test_select_concept_syncs_scenes(self):
        self.project.creative_directions = CONCEPTS["concepts"]
        self.project.save()
        DirectorService().select_concept(self.project, "ugc")
        self.project.refresh_from_db()
        self.assertEqual(self.project.selected_concept_id, "ugc")
        self.assertEqual(self.project.scenes.count(), 5)
        first = self.project.scenes.get(scene_key="scene-1")
        self.assertEqual(first.narration, "Need dinner fast?")
        self.assertEqual((first.metadata or {}).get("status"), "ready")

    def test_select_concept_clears_missing_clip_names(self):
        self.project.creative_directions = CONCEPTS["concepts"]
        self.project.save()
        leftover = Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            title="Stale",
            duration=5,
        )
        leftover.video_clip.name = "ai/scenes/clips/2026/09/missing.mp4"
        leftover.save(update_fields=["video_clip"])
        DirectorService().select_concept(self.project, "ugc")
        first = self.project.scenes.get(scene_key="scene-1")
        self.assertFalse(first.video_clip)
        from ai.serializers import SceneSerializer

        self.assertEqual(SceneSerializer(first).data.get("video_url"), "")

    def test_mix_scenes_between_concepts(self):
        self.project.creative_directions = CONCEPTS["concepts"]
        self.project.save()
        DirectorService().select_concept(
            self.project,
            "ugc",
            [
                {"concept_id": "ugc", "scene_key": "scene-1"},
                {"concept_id": "lifestyle", "scene_key": "scene-2"},
            ],
        )
        scenes = list(self.project.scenes.all())
        self.assertEqual(len(scenes), 5)
        self.assertEqual(scenes[0].narration, "Need dinner fast?")
        self.assertEqual(scenes[1].narration, "Try Serum today.")

    def test_locks_block_script_edits(self):
        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            narration="Keep this",
            caption="Keep caption",
            duration=5,
            metadata={"script_locked": True, "caption_locked": True},
        )
        DirectorService().update_scene(
            scene,
            {"voice_over": "Changed", "on_screen_caption": "Changed", "shot_description": "New shot"},
        )
        scene.refresh_from_db()
        self.assertEqual(scene.narration, "Keep this")
        self.assertEqual(scene.caption, "Keep caption")
        self.assertEqual(scene.visual, "New shot")

    def test_edit_does_not_keep_a_stale_provider_rejection(self):
        from ai.services.director import infer_scene_status

        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-2",
            duration=5,
            generation_status="completed",
            provider="omni",
            provider_request_id="v1_old",
            metadata={"status": "qa_failed", "qa_status": "failed", "error": ""},
        )
        scene.video_clip.save("scene-2.mp4", SimpleUploadedFile("scene-2.mp4", b"clip"), save=True)
        DirectorService().update_scene(scene, {"shot_description": "Updated shot"})
        scene.refresh_from_db()
        self.assertEqual(scene.generation_status, "queued")
        self.assertEqual(scene.provider, "")
        self.assertEqual(scene.failure_code, "")
        self.assertEqual(scene.metadata["status"], "ready")
        self.assertEqual(scene.metadata["pipeline_error"], {})
        self.assertEqual(infer_scene_status(scene), "ready")

    def test_queued_scene_without_provider_error_is_not_rejected(self):
        from ai.services.director import infer_scene_status

        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-2",
            duration=5,
            generation_status="queued",
            metadata={"status": "qa_failed", "error": ""},
        )
        scene.video_clip.save("scene-2.mp4", SimpleUploadedFile("scene-2.mp4", b"clip"), save=True)
        self.assertEqual(infer_scene_status(scene), "ready")

    def test_approved_scene_requires_confirm(self):
        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            duration=5,
            metadata={"approved": True},
        )
        with self.assertRaises(ValueError):
            DirectorService().update_scene(scene, {"shot_description": "No"})

    def test_amendments_update_structured_scenes(self):
        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-2",
            caption="Hello",
            narration="Hello",
            duration=5,
        )
        self.project.qa_results = {
            "checks": [
                {"name": "price", "status": "failed", "detail": "Use the approved price 39.90."}
            ]
        }
        self.project.save()
        recs = AmendmentService().recommend(self.project)
        self.assertTrue(recs)
        AmendmentService().apply(self.project, [recs[0]["id"]], {recs[0]["id"]: "Show RM39.90 at the end."})
        scene.refresh_from_db()
        self.assertIn("RM39.90", scene.caption + scene.narration)
        self.assertTrue((scene.metadata or {}).get("needs_regeneration"))

    def test_brief_can_hide_price_and_url(self):
        brief = {
            "legacy_instructions": "Remove price and URL.",
            "must_not_show": "",
            "offer_price": "RM2599",
        }
        self.assertTrue(suppress_price(brief))
        self.assertTrue(suppress_website(brief))
        cta = commercial_cta(
            brief,
            {"name": "Coach CC TikTok Shop Practical Course", "product_link": "https://coachcc.my/course", "price": "2599"},
            "english",
        )
        self.assertNotIn("2599", cta)
        self.assertNotIn("RM", cta)
        self.assertNotIn("coachcc", cta.lower())

    def test_commercial_cta_does_not_append_product_host(self):
        cta = commercial_cta(
            {"objective": "buy", "offer_price": "RM59"},
            {"name": "Clay Mug", "product_link": "https://coachcc.my/shop"},
            "conversational_bm",
        )
        self.assertIn("Clay Mug", cta)
        self.assertIn("59", cta)
        self.assertNotIn("coachcc", cta.lower())

    def test_compile_prompt_hides_price_and_website(self):
        self.project.product_snapshot = {
            **(self.project.product_snapshot or {}),
            "price": "2599",
            "website": "https://coachcc.my",
            "product_link": "https://coachcc.my/course",
        }
        self.project.creative_brief = normalize_brief(
            {
                "objective": "buy",
                "legacy_instructions": "Remove price and URL.",
                "offer_price": "RM2599",
            },
            self.project,
        )
        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-hide",
            visual="Coach presents the course",
            narration="Join the practical course and start selling with a clear system today.",
            caption="RM2,599 · coachcc.my",
            duration=8,
        )
        DirectorService()._align_captions_to_speech(self.project)
        scene.refresh_from_db()
        self.assertNotIn("2599", scene.caption)
        self.assertNotIn("coachcc", scene.caption.lower())
        self.assertIn("Join the practical course", scene.caption.replace("\n", " "))
        prompt = compile_scene_prompt(scene, self.project)
        self.assertNotIn("2599", prompt)
        self.assertNotIn("coachcc", prompt.lower())
        self.assertIn("show any price", prompt.lower())
        self.assertIn("word for word", prompt.lower())
        self.assertIn("Spoken audio only", prompt)
        self.assertIn("Do not render captions", prompt)
        self.assertIn("Join the practical course", prompt)
        self.assertNotIn("ON-SCREEN CAPTION — REQUIRED", prompt)

    def test_align_captions_match_spoken_audio(self):
        spoken = "Join Coach CC TikTok Shop Practical Course and start selling with a clear system today."
        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-caption",
            narration=spoken,
            caption="Join Coach CC…",
            duration=8,
        )
        DirectorService()._align_captions_to_speech(self.project)
        scene.refresh_from_db()
        flat = scene.caption.replace("\n", " ")
        for word in spoken.split():
            self.assertIn(word, flat)
        self.assertNotIn("…", scene.caption)

    def test_cantonese_captions_follow_nativized_speech(self):
        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-yue",
            narration="这个产品现在可以买了",
            caption="这个产品",
            duration=6,
        )
        self.project.language = "cantonese"
        self.project.save(update_fields=["language"])
        DirectorService()._align_captions_to_speech(self.project)
        scene.refresh_from_db()
        self.assertIn("呢個", scene.narration)
        self.assertIn("而家", scene.narration)
        self.assertEqual(scene.caption.replace("\n", ""), scene.narration.replace("\n", "").replace(" ", ""))

    def test_locked_caption_still_fills_blank_from_audio(self):
        blank = Scene.objects.create(
            project=self.project,
            scene_key="scene-blank",
            narration="Try this balm today.",
            caption="",
            duration=5,
            metadata={"caption_locked": True},
        )
        kept = Scene.objects.create(
            project=self.project,
            scene_key="scene-kept",
            narration="Different spoken line for this scene.",
            caption="Merchant locked caption line",
            duration=5,
            metadata={"caption_locked": True},
        )
        DirectorService()._align_captions_to_speech(self.project)
        blank.refresh_from_db()
        kept.refresh_from_db()
        self.assertIn("Try this balm", blank.caption.replace("\n", " "))
        self.assertIn("Merchant locked caption", kept.caption.replace("\n", " "))
        self.assertNotIn("Different spoken", kept.caption)
        self.assertEqual(kept.narration, "Merchant locked caption line")


class DirectorAPITest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Beauty", slug="beauty")
        self.owner = User.objects.create_user(
            username="apiowner",
            email="api@example.com",
            password="password123",
            name="API Owner",
            mobile="0123111111",
            location="KL",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Dck Beauty",
            description="Skincare",
            location="KL",
        )
        self.product = Product.objects.create(
            brand=self.brand,
            name="Serum",
            description="Daily hydrating serum",
            price="39.90",
            variants=["30ml"],
        )
        ProductImage.objects.create(product=self.product, image=_png())
        self.token = Token.objects.create(user=self.owner)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_save_brief_and_generate_concepts(self):
        saved = self.client.post(
            "/api/ai/video/creative-brief/",
            {
                "product_id": self.product.id,
                "objective": "buy",
                "customer": "Busy Malaysian parents",
                "main_benefit": "Hydrating serum",
                "duration": 30,
            },
            format="json",
        )
        self.assertEqual(saved.status_code, 200)
        project_id = saved.json()["id"]
        self.assertEqual(saved.json()["creative_brief"]["objective"], "buy")
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            return_value=CONCEPTS,
        ):
            response = self.client.post(f"/api/ai/video/{project_id}/concepts/")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()["creative_directions"]), 3)
        self.assertEqual(response.json()["creative_directions"][0]["style"], "ugc")

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_generate_requested_concept_count(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.DRAFT,
        )
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            return_value=CONCEPTS,
        ):
            response = self.client.post(
                f"/api/ai/video/{project.id}/concepts/",
                {"count": 10},
                format="json",
            )
        self.assertEqual(response.status_code, 201, response.content)
        concepts = response.json()["creative_directions"]
        self.assertEqual(len(concepts), 10)
        self.assertEqual(len({item["id"] for item in concepts}), 10)
        self.assertTrue(all(item.get("scenes") for item in concepts))

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_malformed_concepts_fall_back_to_templates(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.DRAFT,
        )
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            return_value={"concepts": [{"title": "broken"}]},
        ):
            response = self.client.post(f"/api/ai/video/{project.id}/concepts/")
        self.assertEqual(response.status_code, 201)
        concepts = response.json()["creative_directions"]
        self.assertEqual(len(concepts), 3)
        self.assertTrue(all(item.get("scenes") for item in concepts))
        self.assertEqual(len({item["style"] for item in concepts}), 3)

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_concepts_fall_back_when_intelligence_is_down(self):
        from ai.exceptions import ProviderError

        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.DRAFT,
        )
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            side_effect=ProviderError("The AI service could not complete this request.", retryable=True),
        ):
            response = self.client.post(f"/api/ai/video/{project.id}/concepts/")
        self.assertEqual(response.status_code, 201)
        concepts = response.json()["creative_directions"]
        self.assertEqual(len(concepts), 3)
        self.assertTrue(all(item.get("scenes") for item in concepts))

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_select_template_concept_on_exported_project(self):
        from ai.exceptions import ProviderError

        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.EXPORTED,
            stage_label="Exported",
            progress=100,
        )
        leftover = Scene.objects.create(
            project=project,
            scene_key="old-hero",
            title="Old exported scene",
            duration=8,
            metadata={
                "status": "generated",
                "qa_status": "failed",
                "pipeline_error": {"stage": "seedance", "detail": "old"},
                "visual_qa": {"frames": ["x"] * 20},
            },
        )
        leftover.video_clip.save("old.mp4", _png(), save=True)
        Scene.objects.create(project=project, scene_key="scene-1", title="Stale", duration=4)
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            side_effect=ProviderError("The AI service could not complete this request.", retryable=True),
        ):
            created = self.client.post(f"/api/ai/video/{project.id}/concepts/")
        self.assertEqual(created.status_code, 201)
        concept_id = created.json()["creative_directions"][0]["id"]
        selected = self.client.post(
            f"/api/ai/video/{project.id}/select-concept/",
            {"concept_id": concept_id},
            format="json",
        )
        self.assertEqual(selected.status_code, 200, selected.content)
        body = selected.json()
        self.assertEqual(body["selected_concept_id"], concept_id)
        self.assertEqual(body["status"], "draft")
        self.assertGreaterEqual(len(body["scenes"]), 3)
        self.assertFalse(any(scene["scene_key"] == "old-hero" for scene in body["scenes"]))
        self.assertTrue(all(not scene.get("video_url") for scene in body["scenes"]))
        bad_mix = self.client.post(
            f"/api/ai/video/{project.id}/select-concept/",
            {"concept_id": concept_id, "scene_mix": "not-a-list"},
            format="json",
        )
        self.assertEqual(bad_mix.status_code, 400)

    def test_select_concept_blocked_while_generating(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            creative_directions=CONCEPTS["concepts"],
            status=VideoProjectStatus.GENERATING_VIDEO,
        )
        response = self.client.post(
            f"/api/ai/video/{project.id}/select-concept/",
            {"concept_id": "ugc"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("already being generated", response.json()["detail"])

    def test_generate_requires_storyboard(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.DRAFT,
        )
        with override_settings(GOOGLE_API_KEY="test-key", GEMINI_API_KEY="test-key"):
            denied = self.client.post(f"/api/ai/video/{project.id}/generate/")
        self.assertEqual(denied.status_code, 400)
        self.assertIn("storyboard", denied.json()["detail"].lower())

    @override_settings(GOOGLE_API_KEY="test-key", GEMINI_API_KEY="test-key")
    def test_select_edit_lock_and_generate_existing_project(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            creative_brief={"generate_character": True},
            creative_directions=CONCEPTS["concepts"],
            status=VideoProjectStatus.DRAFT,
        )
        selected = self.client.post(
            f"/api/ai/video/{project.id}/select-concept/",
            {"concept_id": "ugc"},
            format="json",
        )
        self.assertEqual(selected.status_code, 200)
        scene_id = selected.json()["scenes"][0]["id"]
        locked = self.client.patch(
            f"/api/ai/video/scenes/{scene_id}/",
            {"product_locked": True, "presenter_locked": True, "shot_description": "Locked product shot"},
            format="json",
        )
        self.assertEqual(locked.status_code, 200)
        self.assertTrue(locked.json()["product_locked"])
        ProductImage.objects.create(product=self.product, image=_png())
        with patch("ai.director_views.enqueue_video_generation") as enqueue:
            generated = self.client.post(f"/api/ai/video/{project.id}/generate/")
        self.assertEqual(generated.status_code, 202)
        enqueue.assert_called_once_with(project.id)

    @override_settings(GOOGLE_API_KEY="test-key", GEMINI_API_KEY="test-key")
    def test_generate_after_stop_clears_cancel_flag(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            selected_concept_id="ugc",
            duration_seconds=15,
            creative_brief={
                "pipeline": "studio",
                "cancel_requested": True,
                "cancelled_at": "2026-10-06T19:12:21+00:00",
            },
            status=VideoProjectStatus.FAILED,
            error_message="Stopped by you.",
            stage_label="Stopped",
        )
        for index in range(1, 4):
            Scene.objects.create(
                project=project,
                scene_key=f"scene-{index}",
                order=index,
                title=f"Scene {index}",
                visual="Show product",
                narration="Hello.",
                caption="Hello.",
                duration=5,
                metadata={"status": "ready"},
            )
        ProductImage.objects.create(product=self.product, image=_png())
        with patch("ai.director_views.enqueue_video_generation") as enqueue:
            generated = self.client.post(f"/api/ai/video/{project.id}/generate/")
        self.assertEqual(generated.status_code, 202, generated.data)
        enqueue.assert_called_once_with(project.id)
        project.refresh_from_db()
        self.assertEqual(project.status, VideoProjectStatus.QUEUED)
        self.assertFalse((project.creative_brief or {}).get("cancel_requested"))

    def test_scene_regenerate_uses_existing_pipeline(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY_FOR_REVIEW,
        )
        scene = Scene.objects.create(project=project, scene_key="scene-1", duration=5)
        with override_settings(GEMINI_API_KEY="test-key", GOOGLE_API_KEY="test-key"):
            with patch("ai.director_views.enqueue_scene_regeneration") as enqueue:
                response = self.client.post(f"/api/ai/video/scenes/{scene.id}/regenerate/")
        self.assertEqual(response.status_code, 202)
        enqueue.assert_called_once()
        scene.refresh_from_db()
        self.assertEqual((scene.metadata or {}).get("status"), "regenerating")

    def test_approve_scenes_and_amendments(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY_FOR_REVIEW,
            qa_results={"checks": [{"name": "captions", "status": "warning", "detail": "Caption is clipped."}]},
        )
        scene = Scene.objects.create(project=project, scene_key="scene-1", caption="Hi", duration=5)
        recs = self.client.get(f"/api/ai/video/{project.id}/amendments/")
        self.assertEqual(recs.status_code, 200)
        self.assertTrue(recs.json()["recommendations"])
        approved = self.client.post(
            f"/api/ai/video/{project.id}/approve-scenes/",
            {"scene_ids": [scene.id]},
            format="json",
        )
        self.assertEqual(approved.status_code, 200)
        self.assertTrue(approved.json()["scenes"][0]["approved"])

    @override_settings(GOOGLE_API_KEY="test-key", GEMINI_API_KEY="test-key")
    def test_bulk_generate_starts_selected_concepts_in_parallel(self):
        from ai.services.studio_bulk import expand_studio_bulk_jobs

        jobs = expand_studio_bulk_jobs(
            concept_ids=["ugc", "demo"],
            generate_character=True,
            gender_mode="mix",
            duration_mode="mix",
            count=4,
        )
        self.assertEqual(len(jobs), 4)
        self.assertEqual([job["concept_id"] for job in jobs], ["ugc", "demo", "ugc", "demo"])
        self.assertEqual([job["gender"] for job in jobs], ["female", "male", "female", "male"])
        self.assertEqual([job["duration"] for job in jobs], [15, 30, 45, 60])
        from ai.services.studio_bulk import resolve_bulk_characters

        generated = resolve_bulk_characters(
            [17],
            False,
            ready_ids=[],
            source_generate=True,
        )
        self.assertEqual(generated, [{"character_id": None, "generate_character": True}])
        unready_only = resolve_bulk_characters([17], False, ready_ids=[])
        self.assertEqual(unready_only, [{"character_id": None, "generate_character": True}])
        ready = resolve_bulk_characters([12, 17], True, ready_ids=[12])
        self.assertEqual(
            ready,
            [
                {"character_id": 12, "generate_character": False},
                {"character_id": None, "generate_character": True},
            ],
        )
        covering = expand_studio_bulk_jobs(
            concept_ids=["ugc", "demo", "hero"],
            generate_character=True,
            count=1,
        )
        self.assertEqual(len(covering), 3)
        self.assertEqual({job["concept_id"] for job in covering}, {"ugc", "demo", "hero"})
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            creative_brief={"generate_character": True, "offer_price": "39.90"},
            creative_directions=CONCEPTS["concepts"],
            duration_seconds=30,
            status=VideoProjectStatus.DRAFT,
        )
        with patch("ai.services.studio_bulk.enqueue_video_generation") as enqueue:
            response = self.client.post(
                f"/api/ai/video/{project.id}/bulk-generate/",
                {
                    "concept_ids": ["ugc", "demo"],
                    "generate_character": True,
                    "gender_mode": "mix",
                    "duration_mode": "fixed",
                    "duration_seconds": 15,
                    "count": 2,
                },
                format="json",
            )
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(enqueue.call_count, 2)
        created_ids = [item["id"] for item in response.json()["projects"]]
        self.assertEqual(len(set(created_ids)), 2)
        self.assertNotIn(project.id, created_ids)
        denied = self.client.post(
            f"/api/ai/video/{project.id}/bulk-generate/",
            {"concept_ids": ["ugc"], "generate_character": True, "count": 11},
            format="json",
        )
        self.assertEqual(denied.status_code, 400)
