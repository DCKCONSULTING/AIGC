from django.core.management.base import BaseCommand

from ai.providers.google.client import gemini_credential_status


class Command(BaseCommand):
    help = "Show which credential Gemini and Omni will send. Does not print secrets."

    def handle(self, *args, **options):
        report = gemini_credential_status()
        gemini = report["gemini_api_key"]
        google = report["google_api_key"]
        self.stdout.write("Gemini API credential:")
        self.stdout.write(f"  variable: {gemini['variable']}")
        self.stdout.write(f"  configured: {'YES' if gemini['configured'] else 'NO'}")
        self.stdout.write(f"  used by Gemini/Omni: {'YES' if gemini['used_by_gemini_omni'] else 'NO'}")
        self.stdout.write("GOOGLE_API_KEY:")
        self.stdout.write(f"  configured: {'YES' if google['configured'] else 'NO'}")
        self.stdout.write(f"  used by Gemini/Omni: {'YES' if google['used_by_gemini_omni'] else 'NO'}")
        self.stdout.write("GEMINI_API_KEY:")
        self.stdout.write(f"  configured: {'YES' if gemini['configured'] else 'NO'}")
        self.stdout.write(f"  used by Gemini/Omni: {'YES' if gemini['used_by_gemini_omni'] else 'NO'}")
