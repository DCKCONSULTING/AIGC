from django.core.management.base import BaseCommand

from ai.services.poster import backfill_video_posters


class Command(BaseCommand):
    help = "Create first-screen photos for library videos that do not have one yet."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument(
            "--gemini",
            action="store_true",
            help="Send each extracted frame to Gemini for a finished poster.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit") or None
        saved = backfill_video_posters(enhance=bool(options.get("gemini")), limit=limit)
        self.stdout.write(self.style.SUCCESS(f"Saved {saved} first-screen photos."))
