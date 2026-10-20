from django.core.management.base import BaseCommand, CommandError

from ai.services.misa_seed import (
    BRAND_NAME,
    PASSWORD,
    PRODUCER_EMAIL,
    SeedError,
    collect_summary,
    delete_dataset,
    seed_dataset,
)


class Command(BaseCommand):
    help = "Create the MISA Studio development dataset. --reset deletes only that dataset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete only MISA Demo Brand records and the dedicated test producers.",
        )

    def handle(self, *args, **options):
        try:
            if options["reset"]:
                summary = collect_summary()
                self.stdout.write(self._reset_text(summary))
                delete_dataset()
                self.stdout.write("MISA demo seed records were removed.")
                return
            summary = seed_dataset()
        except SeedError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self._created_text(summary))

    def _reset_text(self, summary: dict) -> str:
        return (
            "MISA TEST DATA RESET\n"
            "\n"
            f"Characters: {summary['characters']}\n"
            f"Products: {summary['products']}\n"
            f"Videos: {summary['videos']}\n"
            f"Storyboards: {summary['storyboards']}\n"
            f"Reviews: {summary['reviews']}\n"
            f"Style Keys: {summary['styles']}\n"
        )

    def _created_text(self, summary: dict) -> str:
        password = (
            f"Password set to {PASSWORD}"
            if summary.get("password_set")
            else "Existing test producer reused; password was not changed."
        )
        return (
            "========================================\n"
            "MISA TEST DATA CREATED\n"
            "========================================\n"
            "\n"
            f"Brand:\n{BRAND_NAME}\n"
            "\n"
            f"Producer:\n{PRODUCER_EMAIL}\n"
            f"{password}\n"
            "\n"
            f"Categories:\n{summary['categories']}\n"
            "\n"
            f"Products:\n{summary['products']}\n"
            "\n"
            f"Characters:\n{summary['characters']}\n"
            "\n"
            f"Character Reference Images:\n{summary['references']}\n"
            "\n"
            f"Style Keys:\n{summary['styles']}\n"
            "\n"
            f"Video Projects:\n{summary['videos']}\n"
            "\n"
            f"Video Character Configs:\n{summary['configs']}\n"
            "\n"
            f"Legacy Presenter Videos:\n{summary['legacy']}\n"
            "\n"
            f"Storyboards:\n{summary['storyboards']}\n"
            "\n"
            f"Storyboard Scenes:\n{summary['scenes']}\n"
            "\n"
            f"Reviews:\n{summary['reviews']}\n"
            "\n"
            "Bulk Generation Test:\n"
            f"{summary['bulk']} products / 1 character\n"
            "\n"
            f"Archived Character:\n{summary['archived']}\n"
            "\n"
            "========================================\n"
        )
