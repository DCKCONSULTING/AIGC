from django.core.management.base import BaseCommand

from commerce.services.ledger import release_matured_commissions


class Command(BaseCommand):
    help = (
        "Move pending commissions whose available_at has passed into the "
        "available wallet bucket. Run on a schedule when commission_hold_days > 0."
    )

    def handle(self, *args, **options):
        released = release_matured_commissions()
        self.stdout.write(self.style.SUCCESS(f"Released {released} matured commission(s)."))
